# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# Install dependencies and register the package (OCR extra for GUI/recommend)
uv sync --extra ocr
uv pip install -e .

# CLI — get augment recommendations for current game
uv run python -m aram_mayhem_helper.cli recommend

# CLI — crawl champion data from Data Dragon
uv run python -m aram_mayhem_helper.cli champion-crawler

# CLI — crawl augment data from OP.GG (with optional page range)
uv run python -m aram_mayhem_helper.cli aram-augment-crawler --start-page 1 --end-page 999

# CLI — crawl augment data from aramkit.com (second data source; version auto-discovered from homepage)
uv run python -m aram_mayhem_helper.cli aramkit-crawler --start-id 1 --end-id 999 --dataset all

# GUI mode (tkinter)
uv run python -m aram_mayhem_helper.gui

# Web — browse cached champion augment data
uv run python -m aram_mayhem_helper.cli web

# Deploy — Docker image installs the main package (no OCR deps)
docker build -t aram-mayhem-helper .
docker run -p 5000:5000 -v /path/to/data:/app/data aram-mayhem-helper

# Lint, format, type-check, test
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/
uv run pytest
```

## Architecture

```text
src/aram_mayhem_helper/
├── cli.py              # CLI entry: cli_main() dispatcher + recommend()/crawler/web subcommands
├── gui.py              # Tkinter GUI (background tasks via queue-bridged threads)
├── algorithm/
│   ├── scoring.py      # add_unit_scale_attr + add_bayesian_sigmoid_score_attr (min-max → Bayesian-sigmoid)
│   ├── pipeline.py     # build_scored_groups(): filter → group by level → score (shared by Suggest & web)
│   └── suggest.py      # Suggest engine: instance-injected thresholds + GameData
├── crawlers/
│   ├── base.py         # BaseCrawler: session / fetch_json / save_to_file / crawl_and_save
│   ├── ddragon/champion_crawler.py
│   ├── opgg/aram_augment_crawler.py
│   └── aramkit/aramkit_crawler.py  # version discovery from homepage HTML
├── league_client_api/
│   └── live_data.py    # Reads current game state from League Client (localhost:2999)
├── ocr/
│   └── ocr_tool.py     # PaddleOCR lazy-loaded; get_ocr_tool() singleton; region_to_pixel(); save_failure_capture(); debug_capture_dir (调试模式保存全部区域截图)
├── web/
│   ├── app.py          # create_app(game_data=None) Flask factory + 3 routes
│   ├── service.py      # i18n names, descriptions, build_champion_list/augments
│   └── templates/index.html
└── utils/
    ├── config.py       # Frozen dataclasses (AppConfig) + load_config() + lazy get_config()
    ├── data.py         # GameData repository + AugmentLookup (lazy singletons via get_game_data())
    ├── aramkit.py      # convert_augment_records + version_sort_key + AramkitResources(dir)
    ├── retry.py        # Typed exponential-backoff retry decorator
    ├── log_config.py   # Root logger setup (console + file)
    └── text_normalization.py  # OCR text cleanup: dash variants (— → -) etc.
tests/                  # pytest: 144 tests + fixtures/ (synthetic data mirroring disk layout)
```

Layering: entry points (cli/gui/web) → algorithm → utils/crawlers. Dependencies point downward only.

## Key Data Flow

**CLI `recommend` flow:**

1. `live_data.get_current_champion_name()` queries League Client API (`https://127.0.0.1:2999/liveclientdata/allgamedata`) for the player's current champion
2. `GameData.champion_id_by_name()` maps champion name → ID (from Data Dragon JSON in `data/ddragon/champions/`)
3. `GameData.available_source()` resolves the data source: default preferred, falls back to the other source when that champion has no file there (avoids `FileNotFoundError` hard-fail for champions missing from one source's crawl)
4. `GameData.augment_entries()` loads that champion's augment stats (opgg reads `data` field; aramkit reads `augments.all` + `convert_augment_records`, both per-(champion, source) cached)
5. `Suggest` runs `build_scored_groups()`: filters placeholders → groups by level → per group `add_unit_scale_attr` (min-max to [0,1]) + `add_bayesian_sigmoid_score_attr` (τ = median(pop>0) × tau_factor, weighted mean/std, sigmoid squash; `weighted_sum` + `performance_norm`/`popular_norm` percentiles)
6. `OCRTool` screenshots 3 predefined screen regions (percentage-based) and runs PaddleOCR to read augment names
7. `Suggest.suggest()` matches OCR results → augment IDs → returns recommendation strings ("快选"/"考虑"/"垃圾"); name-unmatched regions trigger `on_unrecognized` (CLI/GUI wire it to `OCRTool.save_failure_capture`, saving that region's crop to `logs/ocr_failures/` for troubleshooting)

**Web flow:**

- `GET /` serves the SPA (`web/templates/index.html`)
- `GET /api/champions` → `service.build_champion_list()` (per-champion augment counts)
- `GET /api/champions/<id>/augments` → `service.build_champion_augments()` — runs the **same** `build_scored_groups` pipeline as Suggest (`assign_rank=False`, file order preserved) then builds display records (aramkit ×100 scale, i18n names, descriptions)

## Important Details

- **Config is frozen dataclasses**: `load_config()` supports env `ARAM_MAYHEM_CONFIG_DIR`/`ARAM_MAYHEM_DATA_DIR` (required for Docker, where `parents[3]` resolves to site-packages). The old `Config`/`config` compat shim still exists in `utils/config.py` — migrate remaining callers off it when touched. TOML keys accept both `precentage` (legacy) and `percentage` spellings.
- **No import-time side effects**: `get_game_data()`/`get_config()`/`get_ocr_tool()` are lazy singletons; paddle/PIL/screeninfo import inside methods. Importing `aram_mayhem_helper.cli` must not load PaddleOCR.
- **GameData.reload()** clears all caches (champion metadata, entries, translation table, aramkit resources) — GUI calls it after crawls.
- **pipeline tolerances (intentional unification)**: single-item level groups (zero variance → `ValueError`/`ZeroDivisionError`) are logged and skipped, not raised; lookup-miss entries are dropped entirely (legacy Suggest kept them in `champion_augment_data`).
- **OCR screen regions** are module constants `REGIONS` in `ocr/ocr_tool.py` as percentage tuples; `region_to_pixel()` converts. Update if the game UI changes.
- **`Suggest.__init__`** takes `(champion_id, data: GameData, *, source, thresholds: SuggestConfig)` — thresholds are instance data, never read from config at import.
- **`config.toml`** contains thresholds controlling recommendations and the `[ocr] debug_save_captures` debug switch (see README); dead `[team_analysis]` section was removed (feature never merged).
- **Dependencies**: base = flask/numpy(<2.0)/requests; `[ocr]` extra = paddleocr/paddlepaddle/Pillow/screeninfo/setuptools. Web deploy installs the base package only.
- **`data/augment_trans.json`** is the augment name↔ID↔level lookup table, manually maintained. aramkit shares Riot augment IDs; `data/aramkit/resources/{version}/augments.json` is a fallback for missing entries (`AramkitResources`, lazily loaded).
- **Two data sources coexist independently**: OP.GG (`data/opgg/aram_augments/`) and aramkit (`data/aramkit/aram_augments/{dataset}/`). Default source from `[data_source] source`; the web UI switches via the top-bar dropdown / `?source=` param. Both sources are min-max scaled to [0,1] per level group before Bayesian-sigmoid scoring, so scores are directly comparable. aramkit `winRate`/`pickRate` are 0~1 decimals; OP.GG values are 0-100 — no field-level isomorphism.
- **Tests**: pytest (144 tests) with synthetic fixtures in `tests/fixtures/`; coverage gate ≥80% excluding `gui.py`/`ocr_tool.py`; mypy strict + ruff (E/F/I, line-length 120).
- **Console scripts**: `aram-mayhem-helper` (primary) and `main` (deprecated alias) both point to `cli:cli_main`.
