# Newsbrief Automation

A scheduled Python news-briefing project that collects sources, produces summaries, and maintains generated state.

## Requirements

- Python 3.11+
- Dependencies in `requirements.txt`
- Playwright browser dependencies for source collection

## Local setup

```bash
python -m pip install -r requirements.txt
playwright install chromium
python newsbrief.py --all
```

## Automation

The GitHub Actions workflow runs the briefing on a schedule and can also be started manually.

## Repository hygiene

`store.json` is generated application state. Keep only a small example in source control, or store production state outside the repository.
