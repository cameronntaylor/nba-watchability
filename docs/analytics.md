# Anonymous product analytics

NBA Watchability can send anonymous interaction events to PostHog. Analytics are
optional: when no project token is configured, the dashboard runs normally and
does not send events.

## Configure PostHog

1. Create a PostHog Cloud project for NBA Watchability.
2. Copy its **Project token** and confirm whether the project uses the US or EU
   ingest host.
3. In Streamlit Community Cloud, open the app's settings and add:

   ```toml
   [analytics]
   posthog_project_token = "phc_..."
   posthog_host = "https://us.i.posthog.com"
   ```

   For local development, copy `.streamlit/secrets.toml.example` to
   `.streamlit/secrets.toml`, or set `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST`.
4. Restart the app and confirm a `session_started` event appears in PostHog's
   live events view.

The project token is write-only, but it is still kept out of Git so environments
can be changed without code changes. Never add a PostHog personal or secret API
key to this app.

## Event schema

| Event | When it fires | Important properties |
|---|---|---|
| `session_started` | Once per Streamlit session | `identity_scope`, `authentication_required` |
| `slate_viewed` | First view of each slate day in a session | `slate_day`, `games_available` |
| `day_changed` | User changes the day selector | `previous_value`, `new_value` |
| `sort_changed` | User changes All Games sorting | `previous_value`, `new_value`, `slate_day` |
| `filter_changed` | Team, timing, or minimum-score filter changes | `changed_filters`, selected values, result counts, `zero_results` |
| `game_selected` | User clicks a game in the landscape chart | teams, matchup, slate day, score, watchability label |
| `team_view_changed` | User changes League Pass/team-fan view | `previous_value`, `new_value` |
| `favorite_players_changed` | User changes favorite-player choices | selected players and count |
| `team_factors_changed` | User changes team-fan score factors | selected factors and count |

Every event also includes a random session ID, `app=nba-watchability`, and an
analytics schema version. Person profile processing and GeoIP enrichment are
disabled. The implementation does not send names, email addresses, IP-derived
identity, or cross-device identifiers.

## Suggested first dashboard

- Unique sessions: unique `$session_id` on `session_started`.
- Engaged sessions: sessions with any change or game-selection event.
- Filter adoption: sessions with `filter_changed` / sessions started.
- Game-selection rate: sessions with `game_selected` / sessions with
  `slate_viewed`.
- Zero-result rate: `filter_changed` events where `zero_results=true`.
- Popular teams and games: break down `filter_changed.teams` and
  `game_selected.matchup`.

Session identity intentionally resets with a new Streamlit browser session.
Persistent anonymous visitor tracking can be added later if return-rate analysis
becomes important.
