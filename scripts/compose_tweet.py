from datetime import date

def compose_tweet_text():
    today = date.today().strftime("%b %d")

    return (
        f"🏀 NBA Watchability — {today}\n\n"
        "What to watch tonight, ranked by:\n"
        "• expected closeness\n"
        "• team quality\n\n"
        "Built for League Pass fans."
    )