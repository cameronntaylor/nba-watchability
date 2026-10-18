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

| Event | When it fires | Properties specific to the event |
|---|---|---|
| `session_started` | Once per Streamlit session | `identity_scope`, `authentication_required`, `is_returning_visitor`, `visit_number`, `visitor_first_seen_at`, `visitor_persistence` |
| `slate_viewed` | First view of each slate day in a session | `slate_day`, `games_available` |
| `day_changed` | User changes the day selector | `previous_value`, `new_value` |
| `sort_changed` | User changes All Games sorting | `previous_value`, `new_value`, `slate_day` |
| `filter_changed` | Team, timing, or minimum-score filter changes | `changed_filters`, `teams`, `timing`, `minimum_watchability`, `slate_day`, `results_before`, `results_after`, `zero_results` |
| `game_selected` | User clicks a game in the landscape chart | `game_id`, `slate_day`, `matchup`, `away_team`, `home_team`, `watchability`, `watchability_label` |
| `team_view_changed` | User changes League Pass/team-fan view | `previous_value`, `new_value` |
| `favorite_players_changed` | User changes favorite-player choices | `favorite_players`, `favorite_player_count` |
| `team_factors_changed` | User changes team-fan score factors | `team_factors`, `team_factor_count` |

Every event also includes:

- `app = nba-watchability`
- `analytics_schema_version = 1`
- `$session_id`, a random UUID for the current Streamlit session
- `$process_person_profile = false`

The PostHog `distinct_id` is an anonymous `visitor_id` generated in the browser
and saved in first-party `localStorage`. It persists across Streamlit sessions
on the same browser and device, allowing unique-visitor and retention analysis.
The separate `$session_id` changes with each Streamlit session, allowing
visit-level analysis.

Person profile processing and GeoIP enrichment are disabled. The implementation
does not send names, email addresses, IP-derived identity, device fingerprints,
or cross-device identifiers. If local storage is unavailable, events are not
sent; the app does not silently fall back to treating each session as a new
visitor.

## PostHog tutorial

### 1. Confirm events are arriving

1. Open the deployed NBA Watchability app in a private/incognito window.
2. In PostHog, open **Activity** or **Live events**.
3. Look for `session_started` and `slate_viewed`.
4. Change a filter and click a game in the landscape chart. Confirm
   `filter_changed` and `game_selected` appear.
5. Open an event to inspect its properties. Check that its distinct ID begins
   with `anonymous-visitor:`, `$session_id` is present, and
   `$process_person_profile` is `false`.

Events do not appear in PostHog's event picker until PostHog has received the
first event with that name. If nothing arrives, confirm the project token and
ingest host in Streamlit secrets, restart the app, and try again.

### 2. Learn the three screens used most often

- **Activity / Live events** is for debugging individual events and their
  properties.
- **Product analytics** is where you create Trends, Funnels, Retention, and
  other reusable insights.
- **Dashboards** collect saved insights into one monitoring view.

For this app, start with Trends for counts and breakdowns, then use Funnels for
session conversion and Retention for same-browser return visits.

### 3. Create the NBA Watchability dashboard

Go to **Dashboards → New dashboard → Blank dashboard** and name it
`NBA Watchability — Product usage`. Then create and save these insights.

#### Sessions

1. Add a new **Trends** insight.
2. Select the `session_started` event.
3. Use **Total count** as the aggregation. `session_started` fires once per
   Streamlit session.
4. Display it as a number or time series and name it `Sessions`.

#### Unique anonymous visitors

1. Duplicate the Sessions insight.
2. Change the aggregation to **Unique users**.
3. Name it `Unique anonymous visitors`.

The distinction matters: a returning browser can generate multiple sessions but
retains one anonymous distinct ID.

#### New versus returning visits

1. Create a **Trends** insight for `session_started` using **Total count**.
2. Add a breakdown by the `is_returning_visitor` event property.
3. Name it `New vs returning visits`.

`false` represents the first recorded visit for that browser-local ID; `true`
represents later Streamlit sessions from the same browser storage.

#### Visitor retention

1. Add a new **Retention** insight.
2. Use `session_started` as both the starting and returning event.
3. Choose **Unique users**, a daily or weekly period, and the date range you
   want to study.
4. Name it `Anonymous visitor retention`.

This is the clearest view of how often an anonymous browser returns. Use weekly
periods if traffic is low. PostHog's Lifecycle insight is not recommended here
because these events deliberately remain anonymous/personless.

#### Slate exploration funnel

1. Add a new **Funnel** insight.
2. Use `slate_viewed` as step 1.
3. Use `game_selected` as step 2.
4. Choose a conversion window appropriate for a visit, such as one hour.
5. Name it `Slate view → game selected`.

This answers what share of slate-viewing sessions click a specific game.

#### Filter adoption

Create a second funnel with `session_started` followed by `filter_changed` and
name it `Session → filter used`.

#### Zero-result filters

1. Create a **Trends** insight for `filter_changed`.
2. Add an event-property filter where `zero_results` equals `true`.
3. Show total events and name it `Zero-result filter changes`.
4. Duplicate the series without the property filter if you want the failed and
   total filter-change counts side by side.

#### Popular games

1. Create a **Trends** insight for `game_selected`.
2. Add a breakdown by the `matchup` event property.
3. Use a bar chart and name it `Most-selected games`.

#### Control usage

Create a Trends insight with these events as separate series:

- `day_changed`
- `sort_changed`
- `filter_changed`
- `team_view_changed`
- `favorite_players_changed`
- `team_factors_changed`

Name it `Interaction mix`. This shows which controls people actually use.

### 4. Use filters and breakdowns

Click the filter control beside an event series to restrict an insight by an
event property. Useful examples include:

- `filter_changed.changed_filters` to compare team, timing, and score filters
- `filter_changed.timing` to compare Live, Starting soon, and Later
- `sort_changed.new_value` to compare Watchability and Tip time
- `team_view_changed.new_value` to see selected fan views
- `game_selected.watchability_label` to compare Must Watch through Hard Skip

Use a breakdown when you want PostHog to create one series or bar per property
value. Use a filter when you only want a specific subset.

### 5. Read results safely

- Treat **Total count** of `session_started` as sessions and **Unique users** as
  anonymous browsers, not verified people.
- One visitor who returns later can produce another session ID while retaining
  the same visitor ID.
- Clearing site data, using private browsing, or changing browser/device creates
  a new visitor ID; shared browser storage can combine multiple people.
- Because this is not fingerprinting or login-based identity, cross-device
  deduplication is intentionally impossible.
- `slate_viewed` is deduplicated once per slate day within a session.
- A chart selection is tracked when the selected game changes; ordinary hovers
  are not tracked.
- PostHog will not show useful geographic or person-profile analysis because
  this integration deliberately disables both.
- Look at several days of traffic before drawing conclusions from low-volume
  filter or game-selection rates.

### 6. Save and maintain insights

Name every insight clearly, save it to the NBA Watchability dashboard, and set a
consistent date range at the dashboard level. A practical default is the last
30 days grouped daily. Use 7 days for launch monitoring and 90 days for broader
product decisions.

PostHog's official guides cover [Trends](https://posthog.com/docs/product-analytics/trends/overview),
[Funnels](https://posthog.com/docs/product-analytics/funnels), and
[Dashboards](https://posthog.com/docs/product-analytics/dashboards) in more
depth.

The visitor ID remains stable only in the same browser storage. The session ID
intentionally resets with a new Streamlit session.
