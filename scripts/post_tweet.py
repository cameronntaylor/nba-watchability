import os

def post_tweet(text, image_path=None, dry_run=True):
    if dry_run:
        print("DRY RUN — tweet not posted")
        print("Tweet text:")
        print(text)
        if image_path:
            print(f"(would attach image: {image_path})")
        return

    # Import only when actually posting
    import tweepy

    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_SECRET"],
    )

    client.create_tweet(text=text)