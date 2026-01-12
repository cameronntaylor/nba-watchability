import os

def post_tweet(text, image_path=None, dry_run=True):
    if dry_run:
        print("DRY RUN — tweet not posted")
        print(text)
        if image_path:
            print(f"(would attach image: {image_path})")
        return

    import tweepy

    # --- v1.1 API (for media upload) ---
    auth = tweepy.OAuth1UserHandler(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_SECRET"],
    )

    api_v1 = tweepy.API(auth)

    media_id = None
    if image_path:
        media = api_v1.media_upload(image_path)
        media_id = media.media_id

    # --- v2 API (for posting tweet) ---
    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_SECRET"],
    )

    if media_id:
        client.create_tweet(text=text, media_ids=[media_id])
    else:
        client.create_tweet(text=text)