#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dateutil import tz

PT_TZ = tz.gettz("America/Los_Angeles")
UTC_TZ = tz.UTC


def _utc_now() -> dt.datetime:
    return dt.datetime.now(tz=UTC_TZ)


def _iso_z(x: dt.datetime) -> str:
    return x.astimezone(UTC_TZ).isoformat().replace("+00:00", "Z")


def _require_env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _reddit_user_agent() -> str:
    return os.getenv(
        "REDDIT_USER_AGENT",
        "nba-watchability-reddit-volume/0.1 (by u/your_username)",
    ).strip()


def _get_app_only_token(sess: requests.Session, client_id: str, client_secret: str, user_agent: str) -> str:
    url = "https://www.reddit.com/api/v1/access_token"
    r = sess.post(
        url,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Failed to obtain Reddit token.")
    return token


def _request_with_backoff(
    sess: requests.Session,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    timeout: int = 30,
    max_retries: int = 6,
) -> requests.Response:
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            r = sess.request(method, url, headers=headers, params=params, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                wait_s = 2.0 * attempt
                try:
                    retry_after = r.headers.get("Retry-After")
                    if retry_after:
                        wait_s = max(wait_s, float(retry_after))
                except Exception:
                    pass
                time.sleep(wait_s)
                continue
            r.raise_for_status()

            # Respect official API headers when available.
            rem = r.headers.get("x-ratelimit-remaining")
            reset = r.headers.get("x-ratelimit-reset")
            try:
                if rem is not None and reset is not None:
                    rem_f = float(rem)
                    reset_f = float(reset)
                    if rem_f < 1.0:
                        time.sleep(max(1.0, reset_f))
            except Exception:
                pass
            return r
        except Exception as exc:
            last_err = exc
            if attempt >= max_retries:
                break
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"Request failed after retries: {url}") from last_err


def _fetch_listing_since_cutoff(
    sess: requests.Session,
    *,
    subreddit: str,
    listing_type: str,  # "new" | "comments"
    cutoff_utc: dt.datetime,
    until_utc: dt.datetime,
    user_agent: str,
    token: str | None,
    max_pages: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base = "https://oauth.reddit.com" if token else "https://www.reddit.com"
    url = f"{base}/r/{subreddit}/{listing_type}.json"
    headers = {"User-Agent": user_agent}
    if token:
        headers["Authorization"] = f"bearer {token}"

    after: str | None = None
    rows: list[dict[str, Any]] = []
    pages = 0
    min_seen_utc: dt.datetime | None = None

    while True:
        params: dict[str, Any] = {"limit": 100, "raw_json": 1}
        if after:
            params["after"] = after

        r = _request_with_backoff(sess, "GET", url, headers=headers, params=params)
        payload = r.json()
        listing = payload.get("data", {}) if isinstance(payload, dict) else {}
        children = listing.get("children", []) if isinstance(listing, dict) else []
        if not children:
            break

        page_min_utc: dt.datetime | None = None
        for ch in children:
            d = ch.get("data", {}) if isinstance(ch, dict) else {}
            created_utc = d.get("created_utc")
            if created_utc is None:
                continue
            created_dt_utc = dt.datetime.fromtimestamp(float(created_utc), tz=UTC_TZ)

            if page_min_utc is None or created_dt_utc < page_min_utc:
                page_min_utc = created_dt_utc
            if min_seen_utc is None or created_dt_utc < min_seen_utc:
                min_seen_utc = created_dt_utc

            if created_dt_utc < cutoff_utc or created_dt_utc >= until_utc:
                continue

            common = {
                "subreddit": subreddit,
                "id": str(d.get("id") or ""),
                "name": str(d.get("name") or ""),
                "author": str(d.get("author") or ""),
                "created_utc": _iso_z(created_dt_utc),
                "created_pt": created_dt_utc.astimezone(PT_TZ).isoformat(),
                "score": int(d.get("score") or 0),
                "permalink": f"https://reddit.com{d.get('permalink')}" if d.get("permalink") else "",
            }
            if listing_type == "new":
                rows.append(
                    {
                        **common,
                        "content_type": "post",
                        "title": str(d.get("title") or ""),
                        "num_comments": int(d.get("num_comments") or 0),
                        "upvote_ratio": float(d.get("upvote_ratio")) if d.get("upvote_ratio") is not None else None,
                        "is_self": bool(d.get("is_self", False)),
                        "over_18": bool(d.get("over_18", False)),
                    }
                )
            else:
                rows.append(
                    {
                        **common,
                        "content_type": "comment",
                        "title": "",
                        "num_comments": 0,
                        "upvote_ratio": None,
                        "is_self": None,
                        "over_18": None,
                    }
                )

        after = listing.get("after") if isinstance(listing, dict) else None
        pages += 1
        if pages >= max_pages:
            break
        if not after:
            break
        # Since listing is newest -> oldest, stop once this page crosses cutoff.
        if page_min_utc is not None and page_min_utc < cutoff_utc:
            break

    # Listing endpoints can truncate around ~1000 items. Flag likely incompleteness.
    likely_truncated = False
    if min_seen_utc is not None and min_seen_utc > cutoff_utc and pages >= 9:
        likely_truncated = True
    if pages >= max_pages and min_seen_utc is not None and min_seen_utc > cutoff_utc:
        likely_truncated = True

    meta = {
        "pages_fetched": pages,
        "min_seen_utc": _iso_z(min_seen_utc) if min_seen_utc is not None else "",
        "likely_truncated": likely_truncated,
        "listing_type": listing_type,
    }
    return rows, meta


def _build_interval_aggregates(raw_posts: pd.DataFrame, bin_hours: list[int]) -> pd.DataFrame:
    if raw_posts.empty:
        return pd.DataFrame(
            columns=[
                "subreddit",
                "content_type",
                "interval_hours",
                "bucket_start_pt",
                "item_count",
                "num_comments_sum",
                "score_sum",
                "unique_authors",
            ]
        )

    d = raw_posts.copy()
    d["created_pt"] = pd.to_datetime(d["created_pt"], errors="coerce", utc=True).dt.tz_convert(PT_TZ)
    d = d.dropna(subset=["created_pt"])
    d["num_comments"] = pd.to_numeric(d["num_comments"], errors="coerce").fillna(0.0)
    d["score"] = pd.to_numeric(d["score"], errors="coerce").fillna(0.0)

    out_frames: list[pd.DataFrame] = []
    for h in sorted(set(int(x) for x in bin_hours)):
        freq = f"{h}H"
        x = d.copy()
        x["bucket_start_pt"] = x["created_pt"].dt.floor(freq)
        g = (
            x.groupby(["subreddit", "content_type", "bucket_start_pt"], as_index=False)
            .agg(
                item_count=("id", "count"),
                num_comments_sum=("num_comments", "sum"),
                score_sum=("score", "sum"),
                unique_authors=("author", pd.Series.nunique),
            )
            .sort_values(["subreddit", "content_type", "bucket_start_pt"])
            .reset_index(drop=True)
        )
        g["interval_hours"] = h
        out_frames.append(g)

    out = pd.concat(out_frames, ignore_index=True) if out_frames else pd.DataFrame()
    if out.empty:
        return out
    out["bucket_start_pt"] = out["bucket_start_pt"].astype(str)
    return out[
        [
            "subreddit",
            "content_type",
            "interval_hours",
            "bucket_start_pt",
            "item_count",
            "num_comments_sum",
            "score_sum",
            "unique_authors",
        ]
    ]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Fetch subreddit post volume via the official Reddit OAuth API and build interval aggregates."
        )
    )
    p.add_argument("--subreddits", type=str, default="bostonceltics,lakers")
    p.add_argument("--weeks", type=int, default=8)
    p.add_argument("--bin-hours", type=str, default="1,2,4,24")
    p.add_argument("--max-pages", type=int, default=50, help="Max listing pages per subreddit/day window.")
    p.add_argument(
        "--out-raw-csv",
        type=str,
        default=str(Path("data") / "buzz" / "reddit_posts_raw.csv"),
    )
    p.add_argument(
        "--out-raw-parquet",
        type=str,
        default=str(Path("data") / "buzz" / "reddit_posts_raw.parquet"),
    )
    p.add_argument(
        "--out-agg-csv",
        type=str,
        default=str(Path("data") / "buzz" / "reddit_volume_intervals.csv"),
    )
    p.add_argument(
        "--out-agg-parquet",
        type=str,
        default=str(Path("data") / "buzz" / "reddit_volume_intervals.parquet"),
    )
    p.add_argument("--replace", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    subreddits = [s.strip().lower() for s in str(args.subreddits).split(",") if s.strip()]
    bin_hours = [int(x.strip()) for x in str(args.bin_hours).split(",") if x.strip()]

    user_agent = _reddit_user_agent()
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()

    out_raw_csv = Path(args.out_raw_csv)
    out_raw_parquet = Path(args.out_raw_parquet)
    out_agg_csv = Path(args.out_agg_csv)
    out_agg_parquet = Path(args.out_agg_parquet)
    out_raw_csv.parent.mkdir(parents=True, exist_ok=True)
    out_agg_csv.parent.mkdir(parents=True, exist_ok=True)

    sess = requests.Session()
    token: str | None = None
    auth_mode = "public_json"
    if client_id and client_secret:
        token = _get_app_only_token(sess, client_id, client_secret, user_agent)
        auth_mode = "oauth"

    cutoff_utc = (_utc_now().astimezone(PT_TZ) - dt.timedelta(weeks=int(args.weeks))).astimezone(UTC_TZ)
    until_utc = _utc_now()
    all_rows: list[dict[str, Any]] = []
    meta_rows: list[dict[str, Any]] = []
    pulled_at = _iso_z(_utc_now())

    for sub in subreddits:
        for listing_type in ("new", "comments"):
            rows, meta = _fetch_listing_since_cutoff(
                sess,
                subreddit=sub,
                listing_type=listing_type,
                cutoff_utc=cutoff_utc,
                until_utc=until_utc,
                user_agent=user_agent,
                token=token,
                max_pages=int(args.max_pages),
            )
            for r in rows:
                r["pulled_at_utc"] = pulled_at
                r["auth_mode"] = auth_mode
                r["cutoff_utc"] = _iso_z(cutoff_utc)
            all_rows.extend(rows)
            meta_rows.append(
                {
                    "subreddit": sub,
                    "listing_type": listing_type,
                    "auth_mode": auth_mode,
                    "cutoff_utc": _iso_z(cutoff_utc),
                    "pulled_at_utc": pulled_at,
                    **meta,
                }
            )

    raw_new = pd.DataFrame(all_rows)
    if raw_new.empty:
        raw_new = pd.DataFrame(
            columns=[
                "subreddit",
                "id",
                "name",
                "title",
                "author",
                "created_utc",
                "created_pt",
                "content_type",
                "num_comments",
                "score",
                "upvote_ratio",
                "is_self",
                "over_18",
                "permalink",
                "cutoff_utc",
                "auth_mode",
                "pulled_at_utc",
            ]
        )

    if args.replace:
        raw = raw_new.copy()
    else:
        if out_raw_csv.exists():
            try:
                old = pd.read_csv(out_raw_csv)
            except Exception:
                old = pd.DataFrame()
        else:
            old = pd.DataFrame()
        raw = pd.concat([old, raw_new], ignore_index=True)
        if not raw.empty:
            raw = raw.sort_values("pulled_at_utc").drop_duplicates(
                subset=["subreddit", "content_type", "id"], keep="last"
            )
            raw = raw.reset_index(drop=True)

    agg = _build_interval_aggregates(raw, bin_hours=bin_hours)
    meta = pd.DataFrame(meta_rows)

    raw.to_csv(out_raw_csv, index=False)
    agg.to_csv(out_agg_csv, index=False)
    try:
        raw.to_parquet(out_raw_parquet, index=False)
        agg.to_parquet(out_agg_parquet, index=False)
    except Exception:
        pass

    trunc_warn = ""
    if not meta.empty:
        likely = int(meta.get("likely_truncated", pd.Series(dtype=bool)).astype(bool).sum())
        if likely > 0:
            trunc_warn = f" WARNING: {likely} stream(s) likely truncated (listing cap)."

    print(
        f"Mode={auth_mode}. Saved raw items={len(raw_new)} new ({len(raw)} total) and interval rows={len(agg)}. "
        f"Outputs: {out_raw_csv}, {out_agg_csv}.{trunc_warn}"
    )
    if not meta.empty:
        print(meta.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
