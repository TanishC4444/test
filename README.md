# Newsbrief Automation

A news-briefing pipeline with browser-based article extraction, DistilBART summarization, a rolling 30-day store, and permanent weekly archives. It is distinct from Newsies, which uses a local GGUF model.

## Setup

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
playwright install chromium
python newsbrief.py --help
```

On Linux, install CPU PyTorch using its official CPU index first if desired. The requirements file now uses a valid standalone `torch` requirement.

Run a small feed with `python newsbrief.py FEED_URL --max 1 --no-summarize`, or use `--all` for the configured collection. Summarization downloads a model; scraping uses Chromium. The CLI can commit generated state into the current Git repository, including on interruption, so use a deliberate working checkout.

## Offline checks

```sh
python -m unittest test_store -v
```

Checks cover storage round trips, summary preservation, and retaining weekly archives when old rolling entries expire. No scraping, model downloads, or Git commits occur in these checks.

## Current overhead

The default tree contains roughly 1.2 GB of generated data, with additional Git history. Current source was fetched and compared directly without cloning those datasets; it matches the local `tester/newsbrief.py`. No generated archives or unique source were deleted. Moving state to a separate data store is a future migration, not a cleanup already performed.
