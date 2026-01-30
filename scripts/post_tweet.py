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
    import datetime as dt
    import json

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
        try:
            client.create_tweet(text=text, media_ids=media_ids)
        except tweepy.errors.Forbidden as e:
            _handle_forbidden_and_maybe_retry(client, text=text, media_ids=media_ids, err=e, dt_mod=dt, json_mod=json)
    else:
        try:
            client.create_tweet(text=text)
        except tweepy.errors.Forbidden as e:
            _handle_forbidden_and_maybe_retry(client, text=text, media_ids=None, err=e, dt_mod=dt, json_mod=json)


def _handle_forbidden_and_maybe_retry(client, text, media_ids, err, dt_mod, json_mod):
    """
    Twitter API returns 403 for a few common cases (notably duplicate Tweets).
    If we detect a duplicate, retry once with a short timestamp suffix to make the Tweet unique.
    """
    resp = getattr(err, "response", None)
    body_text = None
    body_json = None
    if resp is not None:
        try:
            body_text = resp.text
        except Exception:
            body_text = None
        try:
            body_json = resp.json()
        except Exception:
            body_json = None

    print("Twitter API returned 403 Forbidden.")
    if body_text:
        print("Response body:", body_text)
    elif body_json is not None:
        print("Response JSON:", json_mod.dumps(body_json))

    # Detect duplicate Tweet (commonly error code 187 or message containing "duplicate").
    dup = False
    if isinstance(body_json, dict):
        # v2 errors often look like: {"errors":[{"message":"...","code":187}, ...]}
        errors = body_json.get("errors") or body_json.get("detail") or body_json.get("title")
        if isinstance(errors, list):
            for item in errors:
                try:
                    if int(item.get("code")) == 187:
                        dup = True
                    if "duplicate" in str(item.get("message", "")).lower():
                        dup = True
                except Exception:
                    continue
        if isinstance(errors, str) and "duplicate" in errors.lower():
            dup = True
    if body_text and "duplicate" in body_text.lower():
        dup = True

    if not dup:
        raise err

    suffix = dt_mod.datetime.now(dt_mod.timezone.utc).strftime(" (update %H:%MZ)")
    max_len = 280
    if len(text) + len(suffix) > max_len:
        keep = max(0, max_len - len(suffix) - 1)
        text = text[:keep].rstrip() + "…"
    retry_text = text + suffix

    print("Detected duplicate Tweet; retrying once with timestamp suffix.")
    if media_ids:
        client.create_tweet(text=retry_text, media_ids=media_ids)
    else:
        client.create_tweet(text=retry_text)
