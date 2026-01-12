from datetime import date

def compose_tweet_text():
    today = date.today().strftime("%b %d")

    return (
        f"🏀 NBA Watchability — {today}\n\n"
        "What to watch tonight, ranked by the average Watchability Index which incorporates:\n"
        "• competitiveness\n"
        "• team quality\n"
    )