# Newsbrief Automation

A scheduled Python news-briefing application that collects sources, produces summaries, and maintains generated application state.

## Overview

The project automates a news-briefing workflow and can be run locally or through GitHub Actions. Playwright is used for browser-based source collection.

## Features

- Automated source collection
- News summary generation
- Playwright-based browser automation
- Scheduled GitHub Actions execution
- Manual workflow execution
- Persistent generated state

## Prerequisites

- Python 3.11+
- pip
- Chromium/Playwright browser dependencies

## Installation

```bash
git clone https://github.com/TanishC4444/test.git
cd test
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt
playwright install chromium
```

## Quick Start

```bash
python newsbrief.py --all
```

## Automation

GitHub Actions runs the briefing on a schedule and supports manual execution.

## Repository Hygiene

`store.json` is generated application state. Keep production state outside source control or commit only a small, intentional example.

## Status

Development project.

## License

No separate license is currently specified in the repository.
