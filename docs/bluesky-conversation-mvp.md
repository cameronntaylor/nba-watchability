# Bluesky conversation MVP runbook

This prototype turns a read-only Bluesky capture backup into an operator-review report. It does not change the watchability ranking and it never writes to the captured SQLite database.

## Export the final Render snapshot

1. Resume the suspended Render worker. Do not delete the service or disk.
2. Open the worker's **Shell** and run:

   ```bash
   python scripts/backup_bluesky_capture.py \
     --db /var/data/bluesky.sqlite \
     --author-key-file /var/data/.author_hash_key \
     --output /var/data/bluesky-final.zip \
     --overwrite
   ```

3. Copy the SSH destination from Render's **Connect** menu. On the local Mac, download the file (replace the example destination):

   ```bash
   mkdir -p data/conversation/imports
   scp -s YOUR_RENDER_SSH_DESTINATION:/var/data/bluesky-final.zip data/conversation/imports/
   ```

4. Verify the ZIP before suspending the worker again:

   ```bash
   unzip -t data/conversation/imports/bluesky-final.zip
   shasum -a 256 data/conversation/imports/bluesky-final.zip
   ```

Keep the checksum somewhere outside the ZIP. The archive contains the pseudonymization key and must remain private. `data/conversation/` is gitignored.

## Build the report

From the repository root:

```bash
.venv/bin/python scripts/build_conversation_mvp.py \
  --input data/conversation/imports/bluesky-final.zip
```

The default `as_of` is the newest retained post, not the current clock. This makes a stopped historical capture remain useful.

Outputs are written under `data/conversation/mvp/`:

- `conversation_report.html`: easy local operator view;
- `conversation_report.json`: complete machine-readable prototype output and evidence;
- `topics.csv`: consolidated candidates and 1h/6h/24h metrics;
- `topic_counts_by_hour.csv`: topic time series;
- `team_counts_by_hour.csv`: team time series, including player-to-team attribution;
- `game_associations.csv`: candidate game links, confidence, and suppression reasons.

The script loads current ESPN rosters and the next four schedule dates. Use `--offline` to analyze only direct team mentions without network access.

## Interpretation

This is a short-sample, rules-first prototype. Relative lift is labeled exploratory and appears only when at least seven prior non-overlapping windows of the same size exist. Production Storyline Heat, consumer display eligibility, and ranking effects remain disabled until there is adequate history and operator-reviewed precision.
