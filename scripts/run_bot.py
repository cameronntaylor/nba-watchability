from capture_dashboard import capture_dashboard
from compose_tweet import compose_tweet_text
from post_tweet import post_tweet
import os

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

def main():
    image_paths = capture_dashboard()
    tweet_text = compose_tweet_text()

    if not tweet_text or not str(tweet_text).strip():
        print("No games found / no tweet text generated; skipping tweet.")
        return

    posted = post_tweet(
        text=tweet_text,
        image_paths=image_paths,
        dry_run=DRY_RUN
    )
    if not posted:
        print("Tweet was not posted after retries. Continuing without failing the workflow.")

if __name__ == "__main__":
    main()
