from capture_dashboard import capture_dashboard
from compose_tweet import compose_tweet_text
from post_tweet import post_tweet

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

def main():
    image_path = capture_dashboard()
    tweet_text = compose_tweet_text()

    post_tweet(
        text=tweet_text,
        image_path=image_path,
        dry_run=DRY_RUN
    )

if __name__ == "__main__":
    main()