import os
import tweepy
from pathlib import Path

def post_tweet(
    text: str,
    image_path: Path,
    dry_run: bool = True
):
    if dry_run:
        print("\n--- DRY RUN ---")
        print("Tweet text:\n")
        print(text)
        print("\nImage path:", image_path.resolve())
        print("--- NO TWEET SENT ---\n")
        return

    client = tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_SECRET"]
    )

    auth = tweepy.OAuth1UserHandler(
        os.environ["X_API_KEY"],
        os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_SECRET"]
    )
    api = tweepy.API(auth)

    media = api.media_upload(str(image_path))

    client.create_tweet(
        text=text,
        media_ids=[media.media_id]
    )