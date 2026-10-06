# NBA Watchability
https://nba-watchability.streamlit.app/

https://x.com/NBAWhatToWatch

## Season-transition strategy

- Through Oct. 19, odds come from The Odds API's `basketball_nba_preseason` competition and Team Quality is fixed at 40.
- Beginning Oct. 20, odds use `basketball_nba`. Current-season injuries and the existing quality rules remain active.
- For each team's first ten regular-season games, the Team Quality input is smoothed between its fully healthy prior-season baseline and its current-season adjusted win percentage. Current-season weight is `min(1, games_played / 10)`.
- For the 2025-26 baseline, the champion New York Knicks receive Team Quality 100 and runner-up San Antonio Spurs receive 98.
