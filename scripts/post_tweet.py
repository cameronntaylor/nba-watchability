import os
import time
import json
from pathlib import Path


STATUS_PATH = Path("output/tweet_post_status.json")


def _write_status(payload):
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as err:
        print(f"Failed to write tweet post status: {err}")


def post_tweet(text, image_path=None, image_paths=None, dry_run=True):
    if image_paths is None and image_path is not None:
        image_paths = [image_path]

    if dry_run:
        _write_status(
            {
                "posted": False,
                "dry_run": True,
                "reason": "dry_run",
                "text_preview": str(text)[:280],
                "image_paths": [str(p) for p in (image_paths or [])],
            }
        )
        print("DRY RUN — tweet not posted")
        print(text)
        if image_paths:
            print(f"(would attach images: {image_paths})")
        return True

    import tweepy
    import datetime as dt

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
        media = _retry_media_upload(api_v1, str(p), tweepy)
        media_ids.append(media.media_id)
    if media_ids:
        # Give Twitter a brief moment to make freshly uploaded media consistently attachable.
        time.sleep(3)

    try:
        _post_status_with_retries(
            api_v1,
            text=text,
            media_ids=media_ids or None,
            tweepy_mod=tweepy,
            dt_mod=dt,
            json_mod=json,
        )
        _write_status(
            {
                "posted": True,
                "dry_run": False,
                "reason": "posted",
                "text_preview": str(text)[:280],
                "image_paths": [str(p) for p in (image_paths or [])],
                "media_count": len(media_ids),
            }
        )
        return True
    except tweepy.errors.TwitterServerError as err:
        # Do not fail the whole workflow after screenshots/logs succeeded.
        print(f"Twitter status update failed after retries with server error: {err}")
        _write_status(
            {
                "posted": False,
                "dry_run": False,
                "reason": "twitter_server_error",
                "error_type": type(err).__name__,
                "error_message": str(err),
                "text_preview": str(text)[:280],
                "image_paths": [str(p) for p in (image_paths or [])],
                "media_count": len(media_ids),
            }
        )
        return False
    except tweepy.errors.TooManyRequests as err:
        print(f"Twitter status update failed after retries due to rate limiting: {err}")
        _write_status(
            {
                "posted": False,
                "dry_run": False,
                "reason": "rate_limited",
                "error_type": type(err).__name__,
                "error_message": str(err),
                "text_preview": str(text)[:280],
                "image_paths": [str(p) for p in (image_paths or [])],
                "media_count": len(media_ids),
            }
        )
        return False


def _retry_media_upload(api_v1, path, tweepy_mod):
    delays = [2, 5, 10]
    last_err = None
    for attempt in range(len(delays) + 1):
        try:
            return api_v1.media_upload(path)
        except tweepy_mod.errors.TwitterServerError as err:
            last_err = err
            if attempt >= len(delays):
                raise
            wait_s = delays[attempt]
            print(f"Media upload failed with server error (attempt {attempt + 1}); retrying in {wait_s}s.")
            time.sleep(wait_s)
        except tweepy_mod.errors.TooManyRequests as err:
            last_err = err
            if attempt >= len(delays):
                raise
            wait_s = _retry_after_seconds(err, default=60)
            print(f"Media upload rate-limited (attempt {attempt + 1}); retrying in {wait_s}s.")
            time.sleep(wait_s)
    if last_err is not None:
        raise last_err
    raise RuntimeError("media_upload failed unexpectedly")


def _post_status_with_retries(api_v1, text, media_ids, tweepy_mod, dt_mod, json_mod):
    delays = [5, 15, 30]
    last_err = None
    current_text = text
    for attempt in range(len(delays) + 1):
        try:
            if media_ids:
                api_v1.update_status(status=current_text, media_ids=media_ids)
            else:
                api_v1.update_status(status=current_text)
            if attempt > 0:
                print(f"Tweet posted successfully after {attempt + 1} attempts.")
            return
        except tweepy_mod.errors.Forbidden as err:
            current_text = _handle_forbidden_and_maybe_retry(
                api_v1=api_v1,
                text=current_text,
                media_ids=media_ids,
                err=err,
                dt_mod=dt_mod,
                json_mod=json_mod,
            )
            return
        except tweepy_mod.errors.TwitterServerError as err:
            last_err = err
            if attempt >= len(delays):
                raise
            wait_s = delays[attempt]
            print(f"Twitter status update server error (attempt {attempt + 1}); retrying in {wait_s}s.")
            time.sleep(wait_s)
        except tweepy_mod.errors.TooManyRequests as err:
            last_err = err
            if attempt >= len(delays):
                raise
            wait_s = _retry_after_seconds(err, default=60)
            print(f"Twitter status update rate-limited (attempt {attempt + 1}); retrying in {wait_s}s.")
            time.sleep(wait_s)
    if last_err is not None:
        raise last_err
    raise RuntimeError("status update failed unexpectedly")


def _retry_after_seconds(err, default=60):
    response = getattr(err, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None) or {}
        val = headers.get("retry-after") or headers.get("Retry-After")
        if val:
            try:
                return max(1, int(val))
            except Exception:
                pass
    return default


def _handle_forbidden_and_maybe_retry(api_v1, text, media_ids, err, dt_mod, json_mod):
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
        # v1/v2 errors may include {"errors":[{"message":"...","code":187}, ...]}
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
        api_v1.update_status(status=retry_text, media_ids=media_ids)
    else:
        api_v1.update_status(status=retry_text)
    return retry_text
