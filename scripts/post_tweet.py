import os

def post_tweet(text, image_path=None, image_paths=None, dry_run=True):
    if image_paths is None and image_path is not None:
        image_paths = [image_path]

    if dry_run:
        print("DRY RUN — tweet not posted")
        print(text)
        if image_paths:
            print(f"(would attach images: {image_paths})")
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

    media_ids = []
    for p in image_paths or []:
        media = api_v1.media_upload(str(p))
        media_ids.append(media.media_id)

    # --- v2 API (for posting tweet) ---
    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_SECRET"],
    )

    if media_ids:
        client.create_tweet(text=text, media_ids=media_ids)
    else:
        client.create_tweet(text=text)
