# Bluesky NBA conversation capture

This collector listens to Bluesky's public Jetstream v2 feed, retains likely NBA
posts and replies in SQLite, and saves a resume cursor after every processed event.
It does not require a Bluesky account or API key.

## Start capturing

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/capture_bluesky.py
```

Stop the collector with `Ctrl-C`. Running the same command again resumes from the
last saved cursor. The default database and private author-hashing key are written
under `data/conversation/`, which is excluded from Git.

On the first run, the collector replays the previous five minutes before following
the live tail. Change this with `--lookback-seconds`, or use `--from-live-tip` to
start strictly from the current tip.

For a bounded smoke test:

```bash
python scripts/capture_bluesky.py --max-events 10000 --log-every 1000
```

If a saved cursor is too old for the live replay window, start at the current live
tip while retaining the existing database:

```bash
python scripts/capture_bluesky.py --from-live-tip
```

## What is stored

Only posts that pass the versioned high-recall vocabulary in
`config/bluesky_nba_terms.json` are retained. Author DIDs are converted to keyed
HMAC fingerprints before storage. Creates and updates are idempotent by AT URI;
record deletions, account deactivations, and repository sync markers suppress
previously retained content.

The first-pass vocabulary is intentionally broader than the eventual topic
classifier. Review false positives and false negatives after 24 to 72 hours, then
update the vocabulary version whenever its contents change.

## Operational notes

- Run one collector for a given `stream-id` and database.
- Back up the database and `.author_hash_key` together if author-level counts must
  remain stable.
- Monitor the last cursor time. A stalled process creates a coverage gap rather
  than a valid zero-conversation interval.
- Do not run LLM classification inside the stream loop. Classify retained rows in
  a separate retryable batch job.
