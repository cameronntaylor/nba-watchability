# NBA Watchability
https://nba-watchability.streamlit.app/

https://x.com/NBAWhatToWatch

## Anonymous analytics

The dashboard supports optional, anonymous PostHog product analytics for repeat
visits, slate views, changes to existing day, sort, and personalization controls,
and outbound watch/follow link clicks. It runs normally when analytics is not
configured. Setup details are in [`docs/analytics.md`](docs/analytics.md).

## Season-transition strategy

- Through Oct. 19, odds come from The Odds API's `basketball_nba_preseason` competition and Team Quality is fixed at 40.
- Beginning Oct. 20, odds use `basketball_nba`. Current-season injuries and the existing quality rules remain active.
- For each team's first ten regular-season games, the Team Quality input is smoothed between its fully healthy prior-season baseline and its current-season adjusted win percentage. Current-season weight is `min(1, games_played / 10)`.
- Injury impact shares use the same ramp: prior-season player shares at zero games, then 10% more current-season share per completed game until reaching 100% after ten games.
- For the 2025-26 baseline, the champion New York Knicks receive Team Quality 100 and runner-up San Antonio Spurs receive 98.
