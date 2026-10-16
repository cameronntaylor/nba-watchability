# Deploy the Bluesky collector on Render

The repository includes a Render Blueprint in `render.yaml`. It creates one
continuously running Python background worker and attaches a 1 GB persistent disk
at `/var/data`. The collector database and private author-fingerprinting key are
both stored on that disk.

## One-time account setup

1. Create or sign in to a Render account at <https://dashboard.render.com/>.
2. Connect the GitHub account that can access `cameronntaylor/nba-watchability`.
3. Grant Render access to this repository. Repository-only access is sufficient.
4. In Render, select **New > Blueprint**.
5. Choose the `nba-watchability` repository and the
   `codex/bluesky-conversation-capture` branch.
6. Render should detect the root-level `render.yaml` file and propose one service
   named `nba-watchability-bluesky` with a persistent disk named `bluesky-data`.
7. Review the paid compute and disk charges, then apply the Blueprint.

No Bluesky credentials or application secrets are required. The worker generates
its author-fingerprinting key on the persistent disk during its first start.

## Confirm capture is healthy

Open the worker's **Logs** page. A successful start includes a line similar to:

```text
Connecting to jetstream.us-west.bsky.network (cursor=...)
```

The worker logs a summary every 5,000 processed events. The database totals should
increase while `updated_at` and the cursor remain fresh.

From the worker's **Shell** page, inspect the current database with:

```bash
python scripts/inspect_bluesky_capture.py \
  --db /var/data/bluesky.sqlite \
  --recent 25 \
  --hours 24
```

Export the active retained rows to CSV:

```bash
python scripts/inspect_bluesky_capture.py \
  --db /var/data/bluesky.sqlite \
  --recent 0 \
  --hours 0 \
  --export-csv /var/data/bluesky-export.csv
```

## Create and download a consistent backup

The backup command uses SQLite's online backup API, so it can run while collection
continues. It packages the database and author-fingerprinting key together:

```bash
python scripts/backup_bluesky_capture.py \
  --db /var/data/bluesky.sqlite \
  --author-key-file /var/data/.author_hash_key
```

The command prints the path of the resulting ZIP file under `/var/data`. Add an SSH
public key in Render, copy the worker's SSH command from its **Connect** menu, and
use Render's displayed host with `scp -s` to download the ZIP or CSV to the Mac.

## End the 72-hour experiment

1. Create the ZIP backup and download it.
2. In the worker's Render settings, select **Suspend Service** to stop compute
   charges.
3. Keep the persistent disk if collection will resume soon. The disk continues to
   incur storage charges while retained.
4. Delete the service and disk only after verifying the downloaded backup if the
   experiment is finished permanently.

Restarting or redeploying the worker is safe: collection resumes from the cursor
stored in `/var/data/bluesky.sqlite`. A persistent-disk deployment briefly stops
the worker during a deploy, so avoid unnecessary deploys during the 72-hour sample.
