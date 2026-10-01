from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path
from typing import Any
from typing import Iterable

import pandas as pd
from dateutil import tz

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.team_meta import TEAM_ABBR


PT_TZ = tz.gettz("America/Los_Angeles")
UTC_TZ = tz.UTC
DEFAULT_SLOTS_PT = "08:00,10:00,12:00,14:00,16:00,18:00,20:00"


def _title_case_team(team_key: str) -> str:
    return " ".join(p.capitalize() for p in team_key.split(" "))


def _parse_slots(slots_csv: str) -> list[tuple[int, int]]:
    slots: list[tuple[int, int]] = []
    for part in (slots_csv or "").split(","):
        s = part.strip()
        if not s:
            continue
        hh, mm = s.split(":")
        h = int(hh)
        m = int(mm)
        if h < 0 or h > 23 or m < 0 or m > 59:
            raise ValueError(f"Invalid slot: {s}")
        slots.append((h, m))
    if not slots:
        raise ValueError("No valid slots parsed.")
    return sorted(set(slots))


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _trendreq(*, hl: str, tz_offset_mins: int, retries: int, backoff_s: float) -> Any:
    try:
        from pytrends.request import TrendReq
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "pytrends is required. Install dependencies with `pip install -r requirements.txt`."
        ) from exc
    # retries/backoff are handled in our wrapper below; keep pytrends retries off.
    # Ensure requests don't hang indefinitely (common on flaky networks / throttling).
    return TrendReq(
        hl=hl,
        tz=tz_offset_mins,
        retries=0,
        backoff_factor=0.0,
        requests_args={"timeout": 30},
    )


def _fetch_interest_over_time(
    pytrends: Any,
    keywords: list[str],
    timeframe: str,
    *,
    geo: str,
    retries: int,
    backoff_s: float,
) -> pd.DataFrame:
    for attempt in range(1, retries + 1):
        try:
            pytrends.build_payload(
                kw_list=keywords,
                timeframe=timeframe,
                geo=geo,
                gprop="",
            )
            data = pytrends.interest_over_time()
            if data is None:
                return pd.DataFrame()
            return data.copy()
        except Exception:
            if attempt >= retries:
                raise
            time.sleep(backoff_s * attempt)
    return pd.DataFrame()


def _normalize_time_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    idx = pd.to_datetime(out.index, errors="coerce")
    if getattr(idx, "tz", None) is None:
        idx = idx.tz_localize(UTC_TZ)
    else:
        idx = idx.tz_convert(UTC_TZ)
    out.index = idx
    return out


def _nearest_row_for_slot(day_df: pd.DataFrame, slot_dt_pt: dt.datetime) -> tuple[pd.Timestamp, pd.Series] | None:
    if day_df.empty:
        return None
    # Ensure we operate on a DatetimeIndex and avoid TimedeltaIndex idxmin pitfalls.
    day_df = day_df.sort_index()
    target_utc = pd.Timestamp(slot_dt_pt.astimezone(UTC_TZ))

    idx = day_df.index
    if not isinstance(idx, pd.DatetimeIndex) or idx.empty:
        return None

    nearest_pos = idx.get_indexer([target_utc], method="nearest")[0]
    if nearest_pos < 0:
        return None

    nearest_idx = idx[nearest_pos]
    row = day_df.iloc[nearest_pos]
    return nearest_idx, row


def _sample_slots_for_team_day(
    daily_interest: pd.DataFrame,
    *,
    team_keyword: str,
    team_name: str,
    day_pt: dt.date,
    slots_pt: list[tuple[int, int]],
    geo: str,
    requested_timeframe: str,
    pulled_at_utc: dt.datetime,
) -> list[dict]:
    out: list[dict] = []
    if daily_interest.empty or team_keyword not in daily_interest.columns:
        return out

    day_interest = daily_interest.copy()
    idx_pt = day_interest.index.tz_convert(PT_TZ)
    day_interest = day_interest[(idx_pt.date == day_pt)]
    if day_interest.empty:
        return out

    for hh, mm in slots_pt:
        slot_dt_pt = dt.datetime.combine(day_pt, dt.time(hh, mm), tzinfo=PT_TZ)
        nearest = _nearest_row_for_slot(day_interest, slot_dt_pt)
        if nearest is None:
            continue
        observed_idx_utc, obs_row = nearest
        observed_idx_pt = observed_idx_utc.tz_convert(PT_TZ)
        score = obs_row.get(team_keyword)
        if pd.isna(score):
            continue
        is_partial = bool(obs_row.get("isPartial", False)) if "isPartial" in obs_row.index else False
        out.append(
            {
                "team": team_name,
                "keyword": team_keyword,
                "date_pt": day_pt.isoformat(),
                "slot_label_pt": f"{hh:02d}:{mm:02d}",
                "slot_hour_pt": hh,
                "slot_minute_pt": mm,
                "requested_slot_ts_pt": slot_dt_pt.isoformat(),
                "observed_ts_pt": observed_idx_pt.isoformat(),
                "observed_ts_utc": observed_idx_utc.isoformat(),
                "interest": int(score),
                "is_partial": is_partial,
                "geo": geo,
                "requested_timeframe": requested_timeframe,
                "pulled_at_utc": pulled_at_utc.isoformat(),
            }
        )
    return out


def collect_team_buzz(
    *,
    weeks: int,
    slots_pt: list[tuple[int, int]],
    geo: str,
    hl: str,
    sleep_s: float,
    retries: int,
    backoff_s: float,
    max_days: int | None,
) -> pd.DataFrame:
    today_pt = dt.datetime.now(tz=PT_TZ).date()
    days = [today_pt - dt.timedelta(days=d) for d in range(max(1, weeks * 7))]
    days = sorted(days)
    if max_days is not None:
        days = days[-int(max_days) :]

    team_names = sorted(_title_case_team(k) for k in TEAM_ABBR.keys())
    pytrends = _trendreq(hl=hl, tz_offset_mins=480, retries=retries, backoff_s=backoff_s)

    rows: list[dict] = []
    pulled_at_utc = dt.datetime.now(tz=UTC_TZ)

    for day_pt in days:
        next_day_pt = day_pt + dt.timedelta(days=1)
        timeframe = f"{day_pt.isoformat()}T00 {next_day_pt.isoformat()}T00"
        for kw_group in _chunks(team_names, 5):
            data = _fetch_interest_over_time(
                pytrends,
                kw_group,
                timeframe,
                geo=geo,
                retries=retries,
                backoff_s=backoff_s,
            )
            data = _normalize_time_index(data)
            for team_kw in kw_group:
                rows.extend(
                    _sample_slots_for_team_day(
                        data,
                        team_keyword=team_kw,
                        team_name=team_kw,
                        day_pt=day_pt,
                        slots_pt=slots_pt,
                        geo=geo,
                        requested_timeframe=timeframe,
                        pulled_at_utc=pulled_at_utc,
                    )
                )
            if sleep_s > 0:
                time.sleep(sleep_s)

    if not rows:
        return pd.DataFrame(
            columns=[
                "team",
                "keyword",
                "date_pt",
                "slot_label_pt",
                "slot_hour_pt",
                "slot_minute_pt",
                "requested_slot_ts_pt",
                "observed_ts_pt",
                "observed_ts_utc",
                "interest",
                "is_partial",
                "geo",
                "requested_timeframe",
                "pulled_at_utc",
            ]
        )
    out = pd.DataFrame(rows)
    out = out.sort_values(["date_pt", "slot_hour_pt", "slot_minute_pt", "team"]).reset_index(drop=True)
    return out


def _merge_dedupe(existing: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        return new_rows.copy()
    if new_rows is None or new_rows.empty:
        return existing.copy()
    out = pd.concat([existing, new_rows], ignore_index=True)
    out = out.sort_values("pulled_at_utc")
    out = out.drop_duplicates(subset=["team", "date_pt", "slot_label_pt"], keep="last")
    return out.reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Collect Google Trends team buzz snapshots for NBA teams at fixed PT slots. "
            "Backfills by day for the requested lookback window."
        )
    )
    p.add_argument("--weeks", type=int, default=8, help="Lookback window in weeks (default: 8).")
    p.add_argument("--slots-pt", type=str, default=DEFAULT_SLOTS_PT, help="Comma-separated HH:MM PT slots.")
    p.add_argument("--geo", type=str, default="US", help="Google Trends geo code (default: US).")
    p.add_argument("--hl", type=str, default="en-US", help="Google Trends UI language (default: en-US).")
    p.add_argument("--sleep-s", type=float, default=0.6, help="Sleep between requests in seconds.")
    p.add_argument("--retries", type=int, default=4, help="Retries per request.")
    p.add_argument("--backoff-s", type=float, default=2.0, help="Linear retry backoff base in seconds.")
    p.add_argument("--max-days", type=int, default=None, help="Optional cap on number of backfill days.")
    p.add_argument(
        "--out-csv",
        type=str,
        default=str(Path("data") / "buzz" / "google_trends_team_snapshots.csv"),
        help="Output CSV path.",
    )
    p.add_argument(
        "--out-parquet",
        type=str,
        default=str(Path("data") / "buzz" / "google_trends_team_snapshots.parquet"),
        help="Output Parquet path.",
    )
    p.add_argument(
        "--replace",
        action="store_true",
        help="Replace output instead of merging/deduping by team/date/slot.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    slots_pt = _parse_slots(args.slots_pt)

    out_csv = Path(args.out_csv)
    out_parquet = Path(args.out_parquet)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_parquet.parent.mkdir(parents=True, exist_ok=True)

    new_rows = collect_team_buzz(
        weeks=int(args.weeks),
        slots_pt=slots_pt,
        geo=str(args.geo),
        hl=str(args.hl),
        sleep_s=float(args.sleep_s),
        retries=int(args.retries),
        backoff_s=float(args.backoff_s),
        max_days=int(args.max_days) if args.max_days is not None else None,
    )

    if args.replace:
        merged = new_rows.copy()
    else:
        existing = pd.DataFrame()
        if out_csv.exists():
            try:
                existing = pd.read_csv(out_csv)
            except Exception:
                existing = pd.DataFrame()
        merged = _merge_dedupe(existing, new_rows)

    merged.to_csv(out_csv, index=False)
    try:
        merged.to_parquet(out_parquet, index=False)
    except Exception:
        # Keep CSV as the primary artifact if parquet dependencies differ locally.
        pass

    print(
        f"Saved {len(new_rows)} new rows; total {len(merged)} rows -> "
        f"{out_csv} and {out_parquet}."
    )


if __name__ == "__main__":
    main()
