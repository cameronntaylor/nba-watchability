from capture_dashboard import capture_dashboard
from compose_tweet import compose_tweet_text
from post_tweet import post_tweet
import os

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

def _should_run_now_pt() -> bool:
    # Allow manual runs and local runs without time gating.
    if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return True
    if not os.getenv("GITHUB_ACTIONS"):
        return True

    try:
        from zoneinfo import ZoneInfo
        import datetime as dt
    except Exception:
        return True

    now = dt.datetime.now(tz=ZoneInfo("America/Los_Angeles"))
    if now.minute != 0:
        return False

    # 0=Mon .. 6=Sun
    is_weekday = now.weekday() <= 4
    if is_weekday:
        return now.hour == 12
    return now.hour == 10

def main():
    if not _should_run_now_pt():
        print("Skipping run: not at scheduled PT time.")
        return

    image_paths = capture_dashboard()
    tweet_text = compose_tweet_text()

    post_tweet(
        text=tweet_text,
        image_paths=image_paths,
        dry_run=DRY_RUN
    )

if __name__ == "__main__":
    main()
