from datetime import date

def compose_tweet_text():
    today = date.today().strftime("%b %d")

    return (
        f"🏀 NBA Watchability — {today}\n\n"
        "What to watch tonight, ranked by the Watchability Index which combines:\n"
        "• competitiveness\n"
        "• team quality\n"
    )