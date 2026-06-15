# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# Install dependencies and register the package
uv sync
uv pip install -e .

# CLI — get augment recommendations for current game
uv run python -m aram_mayhem_helper.cli main

# CLI — crawl champion data from Data Dragon
uv run python -m aram_mayhem_helper.cli champion-crawler

# CLI — crawl augment data from OP.GG (with optional page range)
uv run python -m aram_mayhem_helper.cli aram-augment-crawler --start-page 1 --end-page 999

# GUI mode (tkinter)
uv run python -m aram_mayhem_helper.gui

# Web — browse cached champion augment data
uv run python -m aram_mayhem_helper.cli web

# Lint and format
uv run ruff check src/
uv run ruff format src/
```

## Architecture

```text
src/aram_mayhem_helper/
├── cli.py              # CLI entry point with argparse subcommands
├── gui.py              # Tkinter GUI (two buttons + log area)
├── web.py              # Flask web app — champion list + per-champion augment table
├── algorithm/
│   └── suggest.py      # Core: augment recommendation engine
├── crawlers/
│   ├── ddragon/
│   │   └── champion_crawler.py  # Champion JSON from Data Dragon API
│   └── opgg/
│       └── aram_augment_crawler.py  # Augment stats from OP.GG API
├── league_client_api/
│   └── live_data.py    # Reads current game state from League Client (localhost:2999)
├── ocr/
│   └── ocr_tool.py     # PaddleOCR-based screen capture + text recognition
└── utils/
    ├── config.py       # TOML config loader (Config singleton with nested key access)
    ├── data.py         # Game data: Data (champion list), ChampionAugmentData, AugmentTool (name↔ID)
    ├── norm.py         # IQR-filtered min-max/z-score normalization + weighted sum
    ├── retry.py        # Exponential backoff retry decorator
    ├── log_config.py   # Root logger setup (console + file)
    └── text_normalization.py  # OCR text cleanup: normalizes dash variants (— → -) etc.
```

## Key Data Flow

**CLI `main` flow:**

1. `live_data.py` queries League Client API (`https://127.0.0.1:2999/liveclientdata/allgamedata`) to get the player's current champion name
2. `data.Data` maps champion name → champion ID (from Data Dragon JSON in `data/ddragon/champions/`)
3. `ChampionAugmentData` loads that champion's augment stats from `data/opgg/aram_augments/{championId}.json`
4. `Suggest` normalizes performance/popularity scores (IQR min-max), computes weighted sum (0.7 perf + 0.3 popular), ranks augments within each level
5. `OCRTool` screenshots 3 predefined screen regions (percentage-based) and runs PaddleOCR to read augment names
6. `Suggest.suggest()` matches OCR results → augment IDs → returns recommendation strings ("快选"/"考虑"/"垃圾")

**Data crawling:**

- `champion-crawler`: Fetches `https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json` → saves to `data/ddragon/champions/{version}.json`
- `aram-augment-crawler`: Iterates champion IDs, fetches `https://lol-api-champion.op.gg/api/contents/stats/champions/{id}/aram-augments` → saves to `data/opgg/aram_augments/{id}.json`

**Web flow:**

- `GET /` serves a single-page app (inline HTML rendered via `render_template_string`)
- Home page shows a champion card grid from `GET /api/champions` (returns champion ID, name, augment count)
- Clicking a champion calls `GET /api/champions/<id>/augments` → `_build_champion_augments()` applies the same IQR min-max normalization + weighted-sum logic as `Suggest`, then returns per-champion records with `augment_name` resolved from `augment_tool`
- Detail view supports sorting by any column, level checkboxes, and min-performance/min-popularity numeric filters

## Important Details

- **League Client must be running** with "allow third-party apps" enabled for CLI `main` and GUI to work. The API uses self-signed certs — SSL verification is disabled via `urllib3.disable_warnings()`.
- **OCR screen regions** are hardcoded in `OCRTool.REGIONS` as percentage tuples `(left%, top%, right%, bottom%)`. If the game UI changes, these coordinates need updating.
- **`Suggest.__init__` filters out** augment entries where `performance == 170` and `popular == 0` — these are treated as invalid/placeholder data points.
- **`config.toml`** contains thresholds that control recommendation behavior: `immediate_select_weighted_sum_threshold` (0.6), `immediate_select_precentage_threshold` (0.15), etc.
- **No tests exist** in this project. The `ruff` config in `pyproject.toml` enables only `E`, `F`, `I` rules.
- **`utils/text_normalization.py`** normalizes OCR text before augment name lookup. PaddleOCR may misread `-` (U+002D) as `—` (em-dash), `–` (en-dash), or `－` (fullwidth). `AugmentTool.get_augment_id()` applies `normalize_text()` before the exact dict match.
- **`data/augment_trans.json`** is the augment name↔ID↔level lookup table, manually maintained. The module-level singletons `data`, `champion_augment_data_dict`, and `augment_tool` in `data.py` are initialized at import time.
