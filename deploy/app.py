"""ARAM 符文数据浏览 — 独立部署版。

零依赖 aram_mayhem_helper 包，仅需 flask + numpy。
启动: python app.py
"""

import json
import logging
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, render_template_string, request

# ── Paths (relative to this file) ──────────────────────────────────────────
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
CHAMPIONS_DIR = DATA_DIR / "ddragon" / "champions"
AUGMENTS_DIR = DATA_DIR / "opgg" / "aram_augments"
# aramkit 数据集子目录: all 全体 / high 高分段
ARAMKIT_DATASET = "all"
ARAMKIT_DIR = DATA_DIR / "aramkit" / "aram_augments" / ARAMKIT_DATASET
ARAMKIT_RESOURCES_DIR = DATA_DIR / "aramkit" / "resources"
TRANS_FILE = DATA_DIR / "augment_trans.json"
I18N_FILE = DATA_DIR / "champions-names-i18n.json"
AUG_DESC_FILE = DATA_DIR / "aram-mayhem-augments.zh_cn.json"

# 默认数据源: "opgg" | "aramkit"
DEFAULT_SOURCE = "opgg"
# aramkit rarity → level（2=棱彩, 1=黄金, 0=白银）
RARITY_TO_LEVEL = {"prismatic": "2", "gold": "1", "silver": "0"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Normalization — Bayesian shrinkage + sigmoid squash (inlined)
# ═══════════════════════════════════════════════════════════════════════════

# Configurable defaults (no TOML dependency in standalone deploy)
SHRINKAGE_TAU_FACTOR = 0.5
SIGMOID_STEEPNESS = 1.0


def add_bayesian_sigmoid_score_attr(
    data_list: list,
    perf_attr: str = "performance",
    pop_attr: str = "popular",
    new_attr: str = "weighted_sum",
    tau_factor: float = SHRINKAGE_TAU_FACTOR,
    sigmoid_steepness: float = SIGMOID_STEEPNESS,
    perf_display_attr: str = "",
    pop_display_attr: str = "",
) -> None:
    """Bayesian shrinkage + sigmoid squash into [0,1] in one pass.

    Auto-tau: τ = median(pop > 0) × tau_factor
    Shrinkage: adjusted = (pop/(pop+τ))×perf + (τ/(pop+τ))×level_mean
    Sigmoid: final = 1 / (1 + exp(-(adjusted - level_mean) / (level_std × steepness)))
    """
    if not data_list:
        raise ValueError("data_list is empty")

    perf_arr = np.array([float(item[perf_attr]) for item in data_list])
    pop_arr = np.array([float(item[pop_attr]) for item in data_list])

    level_mean = float(np.average(perf_arr, weights=pop_arr))
    level_var = float(np.average((perf_arr - level_mean) ** 2, weights=pop_arr))
    level_std = float(np.sqrt(level_var))

    if level_std == 0:
        raise ValueError("performance std is 0")

    positive_pop = pop_arr[pop_arr > 0]
    tau = float(np.median(positive_pop)) * tau_factor if len(positive_pop) > 0 else 0.1 * tau_factor

    # Pre-compute popularity percentiles (1.0 = most popular)
    pop_percentiles = {}
    if pop_display_attr:
        n = len(data_list)
        sorted_indices = sorted(range(n), key=lambda i: float(data_list[i][pop_attr]), reverse=True)
        for rank, idx in enumerate(sorted_indices):
            pop_percentiles[idx] = 1.0 - rank / max(n - 1, 1)

    for idx, item in enumerate(data_list):
        perf = float(item[perf_attr])
        pop = float(item[pop_attr])
        denom = pop + tau
        weight = pop / denom if denom > 0 else 0.0
        adjusted = weight * perf + (1.0 - weight) * level_mean
        divisor = level_std * sigmoid_steepness
        z = (adjusted - level_mean) / divisor if divisor > 0 else 0.0
        final_score = 1.0 / (1.0 + np.exp(-z))
        item[new_attr] = round(float(final_score), 4)

        # Per-dimension display values
        if perf_display_attr:
            perf_z = (perf - level_mean) / divisor if divisor > 0 else 0.0
            item[perf_display_attr] = round(float(1.0 / (1.0 + np.exp(-perf_z))), 4)
        if pop_display_attr:
            item[pop_display_attr] = round(pop_percentiles[idx], 4)


def add_unit_scale_attr(
    data_list: list,
    perf_attr: str = "performance",
    pop_attr: str = "popular",
    perf_unit_attr: str = "performance_unit",
    pop_unit_attr: str = "popular_unit",
) -> None:
    """Min-max scale performance/popular into [0,1], writing new fields (raw values kept).

    Unifies the scale of different data sources (OP.GG 0-100 vs aramkit 0-1)
    before the Bayesian shrinkage step.
    """
    if not data_list:
        return
    for src_attr, new_attr in ((perf_attr, perf_unit_attr), (pop_attr, pop_unit_attr)):
        values = [float(item[src_attr]) for item in data_list]
        min_val, max_val = min(values), max(values)
        if max_val == min_val:
            for item in data_list:
                item[new_attr] = 0.0
        else:
            for item in data_list:
                item[new_attr] = round((float(item[src_attr]) - min_val) / (max_val - min_val), 4)


def convert_augment_records(augment_list: list[dict]) -> list[dict]:
    """Convert aramkit augment records to engine-standard records (native 0-1 values)."""
    converted: list[dict] = []
    for item in augment_list:
        item_id = item.get("id")
        win_rate = item.get("winRate")
        pick_rate = item.get("pickRate")
        if item_id is None or win_rate is None or pick_rate is None:
            continue
        record = {
            "id": item_id,
            "performance": float(win_rate),
            "popular": float(pick_rate),
        }
        for key in ("sampleCount", "rank", "stageAgnostic", "availableStages"):
            if key in item:
                record[key] = item[key]
        converted.append(record)
    return converted


# ═══════════════════════════════════════════════════════════════════════════
# Data loading (inlined from aram_mayhem_helper.utils.data)
# ═══════════════════════════════════════════════════════════════════════════


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_champion_data() -> dict[str, dict]:
    """Load champion name→key mapping from the latest Data Dragon file."""
    if not CHAMPIONS_DIR.exists():
        logger.error(f"英雄数据目录不存在: {CHAMPIONS_DIR}")
        return {}
    files = sorted(CHAMPIONS_DIR.iterdir(), key=lambda f: f.name, reverse=True)
    for f in files:
        if f.suffix == ".json":
            raw = _load_json(f)
            return raw.get("data", {})
    return {}


def _build_champion_id_name_map() -> dict[str, str]:
    """Return {champion_key: champion_name}."""
    mapping: dict[str, str] = {}
    for _cid, info in _load_champion_data().items():
        key = info.get("key")
        name = info.get("name")
        if key and name:
            mapping[key] = name
    return mapping


def _load_augment_trans() -> dict[str, dict]:
    """Load augment ID→{name, level} translation table."""
    if TRANS_FILE.exists():
        return _load_json(TRANS_FILE)
    return {}


# Module-level caches (populated once at startup)
CHAMPION_NAMES: dict[str, str] = {}
CHAMPION_I18N: dict[str, dict] = {}
AUGMENT_TRANS: dict[str, dict] = {}


def _load_champion_i18n() -> dict[str, dict]:
    if I18N_FILE.exists():
        try:
            return json.loads(I18N_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"读取英雄 i18n 文件失败: {e}")
    return {}


def champion_display_name(cid: str) -> str:
    info = CHAMPION_I18N.get(cid, {})
    titles = info.get("titles", {})
    return titles.get("zh-CN", "") or info.get("alias", "")


def champion_alias(cid: str) -> str:
    info = CHAMPION_I18N.get(cid, {})
    return info.get("alias", "")


def _load_augment_descriptions() -> dict[str, dict]:
    if AUG_DESC_FILE.exists():
        try:
            return json.loads(AUG_DESC_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"读取符文描述文件失败: {e}")
    return {}


AUGMENT_DESCRIPTIONS: dict[str, dict] = {}


def augment_description(aug_id: str) -> str:
    """Return cleaned description text for an augment."""
    import re

    info = AUGMENT_DESCRIPTIONS.get(aug_id, {})
    desc = info.get("description", "") or info.get("tooltip", "")
    return re.sub(r"<[^>]+>", "", desc)


def init_data() -> None:
    """Pre-load champion names and augment translations into memory."""
    global CHAMPION_NAMES, CHAMPION_I18N, AUGMENT_TRANS, AUGMENT_DESCRIPTIONS
    CHAMPION_NAMES = _build_champion_id_name_map()
    CHAMPION_I18N = _load_champion_i18n()
    AUGMENT_TRANS = _load_augment_trans()
    AUGMENT_DESCRIPTIONS = _load_augment_descriptions()
    logger.info(
        f"已加载 {len(CHAMPION_NAMES)} 个英雄, {len(CHAMPION_I18N)} 条 i18n, "
        f"{len(AUGMENT_TRANS)} 条符文翻译, {len(AUGMENT_DESCRIPTIONS)} 条符文描述"
    )


def get_champion_name(cid: str) -> str | None:
    return CHAMPION_NAMES.get(cid)


# ── aramkit resources fallback (lazy) ──────────────────────────────────────

ARAMKIT_AUGMENT_INFO: dict[str, dict] = {}
ARAMKIT_AUGMENT_NAME_IDS: dict[str, str] = {}
_ARAMKIT_LOADED = False


def _load_aramkit_resources() -> None:
    """Lazily load the newest aramkit resources dir into in-memory maps."""
    global ARAMKIT_AUGMENT_INFO, ARAMKIT_AUGMENT_NAME_IDS, _ARAMKIT_LOADED
    if _ARAMKIT_LOADED:
        return
    _ARAMKIT_LOADED = True
    if not ARAMKIT_RESOURCES_DIR.exists():
        return
    version_dirs = [d for d in ARAMKIT_RESOURCES_DIR.iterdir() if d.is_dir()]
    if not version_dirs:
        return
    latest_dir = max(version_dirs, key=lambda d: d.name)
    aug_file = latest_dir / "augments.json"
    if not aug_file.exists():
        return
    try:
        raw = _load_json(aug_file)
    except Exception as e:
        logger.warning(f"读取 aramkit 资源文件失败: {e}")
        return
    info: dict[str, dict] = {}
    name_ids: dict[str, str] = {}
    for aug_id, entry in raw.items():
        name = entry.get("name")
        if not name:
            continue
        level = RARITY_TO_LEVEL.get(entry.get("rarity"), "0")
        info[aug_id] = {"name": name, "level": level}
        name_ids[name] = aug_id
    ARAMKIT_AUGMENT_INFO = info
    ARAMKIT_AUGMENT_NAME_IDS = name_ids


def get_augment_info(aug_id: str, source: str = DEFAULT_SOURCE) -> dict | None:
    """翻译表优先；aramkit 缺失时回退其资源文件。"""
    info = AUGMENT_TRANS.get(aug_id)
    if info is None and source == "aramkit":
        _load_aramkit_resources()
        info = ARAMKIT_AUGMENT_INFO.get(aug_id)
    return info


def get_augment_id(augment_name: str, source: str = DEFAULT_SOURCE) -> str | None:
    """按名称反查 ID：翻译表优先；aramkit 缺失时回退其资源文件。"""
    for aug_id, entry in AUGMENT_TRANS.items():
        if entry.get("name") == augment_name:
            return aug_id
    if source == "aramkit":
        _load_aramkit_resources()
        return ARAMKIT_AUGMENT_NAME_IDS.get(augment_name)
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Data aggregation
# ═══════════════════════════════════════════════════════════════════════════


def _list_cached_champion_ids(source: str = DEFAULT_SOURCE) -> list[str]:
    """Return sorted list of champion IDs that have cached augment data."""
    data_dir = ARAMKIT_DIR if source == "aramkit" else AUGMENTS_DIR
    if not data_dir.exists():
        return []
    return sorted(
        [f.stem for f in data_dir.iterdir() if f.suffix == ".json"],
        key=int,
    )


def build_champion_list(source: str = DEFAULT_SOURCE) -> list[dict]:
    champions: list[dict] = []
    data_dir = ARAMKIT_DIR if source == "aramkit" else AUGMENTS_DIR
    for cid in _list_cached_champion_ids(source):
        cname = get_champion_name(cid)
        if not cname:
            continue
        aug_file = data_dir / f"{cid}.json"
        count = 0
        try:
            raw = _load_json(aug_file)
            if source == "aramkit":
                entries = convert_augment_records(raw.get("augments", {}).get("all", []))
            else:
                entries = raw.get("data", [])
            count = sum(
                1
                for e in entries
                if e.get("performance") is not None and e.get("popular", 0) != 0 and e.get("id") is not None
            )
        except Exception:
            count = 0
        champions.append(
            {
                "champion_id": cid,
                "champion_name": cname,
                "champion_name_cn": champion_display_name(cid),
                "champion_alias": champion_alias(cid),
                "augment_count": count,
            }
        )
    return champions


def build_champion_augments(champion_id: str, source: str = DEFAULT_SOURCE) -> list[dict]:
    cname = get_champion_name(champion_id)
    if not cname:
        return []

    data_dir = ARAMKIT_DIR if source == "aramkit" else AUGMENTS_DIR
    aug_file = data_dir / f"{champion_id}.json"
    try:
        raw = _load_json(aug_file)
        if source == "aramkit":
            entries = convert_augment_records(raw.get("augments", {}).get("all", []))
        else:
            entries = raw.get("data", [])
    except Exception:
        logger.warning(f"无法读取英雄 {champion_id} 的符文数据")
        return []

    rows: list[dict] = []
    by_level: dict[str, list[dict]] = {}

    for entry in entries:
        perf = entry.get("performance")
        pop = entry.get("popular")
        if perf is None or pop is None:
            continue
        if pop == 0:
            continue

        item_id = entry.get("id")
        if item_id is None:
            continue

        aug_info = get_augment_info(str(item_id), source)
        if not aug_info:
            continue

        level = aug_info.get("level", "?")
        augment_name = aug_info.get("name", f"ID:{item_id}")

        record = {
            "champion_id": champion_id,
            "champion_name": cname,
            "champion_name_cn": champion_display_name(champion_id),
            "champion_alias": champion_alias(champion_id),
            "augment_id": str(item_id),
            "augment_name": augment_name,
            "description": augment_description(str(item_id)),
            "level": level,
            "performance": perf,
            "popular": pop,
        }
        rows.append(record)
        by_level.setdefault(level, []).append(record)

    for level, level_items in by_level.items():
        try:
            # 统一数据源尺度：performance/popular 先 min-max 缩放到 [0,1]
            add_unit_scale_attr(level_items)
            add_bayesian_sigmoid_score_attr(
                level_items,
                perf_attr="performance_unit",
                pop_attr="popular_unit",
                new_attr="weighted_sum",
                tau_factor=SHRINKAGE_TAU_FACTOR,
                sigmoid_steepness=SIGMOID_STEEPNESS,
                perf_display_attr="performance_norm",
                pop_display_attr="popular_norm",
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"英雄 {cname} 等级 {level} 归一化失败: {e}")

    # 计算误解指数（陷阱得分）：popular_norm × (1 − performance_norm)
    for record in rows:
        pn = record.get("popular_norm", 0)
        fn = record.get("performance_norm", 0)
        record["misconception"] = round(pn * (1 - fn), 4)
        record["is_trap"] = pn > 0.5 and fn < 0.5

    return rows


# ═══════════════════════════════════════════════════════════════════════════
# HTML template (same as web.py)
# ═══════════════════════════════════════════════════════════════════════════

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ARAM 符文数据浏览</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif;
    background: #1a1a2e; color: #e0e0e0;
    display: flex; flex-direction: column; height: 100vh; overflow: hidden;
  }
  .top-bar {
    background: linear-gradient(135deg, #16213e 0%, #0f3460 100%);
    padding: 12px 32px; border-bottom: 2px solid #e94560;
    display: flex; align-items: center; gap: 16px; flex-shrink: 0;
  }
  .top-bar h1 { font-size: 1.3rem; color: #e94560; }
  .top-bar .back-btn {
    display: none; padding: 5px 12px; border: 1px solid #e94560; border-radius: 4px;
    background: transparent; color: #e94560; cursor: pointer; font-size: 0.8rem;
    transition: background 0.15s;
  }
  .top-bar .back-btn:hover { background: rgba(233, 69, 96, 0.15); }
  .top-bar .back-btn.show { display: inline-block; }
  .top-bar .source-select {
    padding: 5px 10px; border: 1px solid #0f3460; border-radius: 4px;
    background: #1a1a2e; color: #e0e0e0; font-size: 0.85rem; cursor: pointer;
  }
  .top-bar .source-select:focus { outline: none; border-color: #e94560; }
  .top-bar .subtitle { font-size: 0.85rem; color: #a0a0b0; margin-left: auto; }
  .search-bar {
    padding: 10px 32px; background: #16213e; border-bottom: 1px solid #0f3460;
    display: flex; gap: 12px; align-items: center; flex-shrink: 0;
  }
  .search-bar input[type="text"] {
    padding: 8px 12px; border: 1px solid #0f3460; border-radius: 4px;
    background: #1a1a2e; color: #e0e0e0; font-size: 0.9rem; width: 260px;
  }
  .search-bar input[type="text"]:focus { outline: none; border-color: #e94560; }
  .count-label { font-size: 0.8rem; color: #a0a0b0; }

  /* ---------- Champion grid ---------- */
  #championView { flex: 1; overflow-y: auto; padding: 20px 32px; }
  .champ-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 10px;
  }
  .champ-card {
    background: #16213e; border: 1px solid #0f3460; border-radius: 8px;
    padding: 14px; cursor: pointer; transition: all 0.15s; text-align: center;
  }
  .champ-card:hover { border-color: #e94560; transform: translateY(-2px); }
  .champ-card .name { font-size: 0.95rem; font-weight: 600; color: #e0e0e0; }
  .champ-card .alias { font-size: 0.7rem; color: #7a7a8a; margin-top: 2px; }
  .champ-card .count { font-size: 0.7rem; color: #7ab8f5; margin-top: 4px; }

  /* ---------- Detail view ---------- */
  #detailView { display: none; flex-direction: column; flex: 1; overflow: hidden; }
  #detailView.show { display: flex; }
  #championView.hidden { display: none; }
  .detail-bar {
    display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: center;
    padding: 8px 32px; background: #16213e; border-bottom: 1px solid #0f3460;
    flex-shrink: 0;
  }
  .detail-bar label { font-size: 0.8rem; color: #a0a0b0; display: flex; align-items: center; gap: 4px; }
  .detail-bar input[type="checkbox"] { accent-color: #e94560; }
  .detail-bar input[type="number"] {
    padding: 4px 6px; border: 1px solid #0f3460; border-radius: 4px;
    background: #1a1a2e; color: #e0e0e0; font-size: 0.8rem; width: 72px;
  }
  .detail-bar input[type="number"]:focus { outline: none; border-color: #e94560; }
  .detail-bar .filter-group {
    display: flex; align-items: center; gap: 4px;
    border-left: 1px solid #0f3460; padding-left: 12px;
  }
  .table-wrap {
    flex: 1; overflow: auto; border-top: 1px solid #0f3460;
  }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  thead th {
    position: sticky; top: 0; z-index: 5;
    background: #0f3460; color: #e0e0e0; padding: 10px 14px;
    text-align: left; cursor: pointer; user-select: none;
    white-space: nowrap; border-bottom: 2px solid #e94560;
    transition: background 0.15s;
  }
  th:hover { background: #1a4a7a; }
  th .arrow { font-size: 0.7rem; margin-left: 4px; opacity: 0.4; }
  th.sorted .arrow { opacity: 1; }
  td { padding: 8px 14px; border-bottom: 1px solid #0f3460; white-space: nowrap; }
  .aug-name { cursor: help; }
  #tooltip {
    display: none; position: fixed; z-index: 9999;
    max-width: 360px; padding: 8px 12px;
    background: #0f3460; color: #e0e0e0; font-size: 0.8rem;
    border: 1px solid #e94560; border-radius: 6px;
    white-space: normal; word-break: break-word;
    pointer-events: none; line-height: 1.5;
    box-shadow: 0 4px 12px rgba(0,0,0,0.5);
  }
  tr:hover td { background: rgba(233, 69, 96, 0.06); }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .level-badge {
    display: inline-block; min-width: 20px; text-align: center;
    padding: 2px 8px; border-radius: 10px; font-size: 0.75rem; font-weight: 600;
  }
  .level-0 { background: #4a4a5a; color: #c0c0c0; }
  .level-1 { background: #1a4a7a; color: #7ab8f5; }
  .level-2 { background: #5a3a6a; color: #c89ef5; }
  .ws-high { color: #4caf50; font-weight: 600; }
  .ws-mid { color: #ff9800; }
  .ws-low { color: #f44336; }

  /* Trap card */
  .trap-card {
    display: none; margin: 12px 32px; padding: 12px 16px;
    background: linear-gradient(135deg, #2a1a1e 0%, #1a1a2e 100%);
    border: 1px solid #e94560; border-radius: 8px;
  }
  .trap-card.show { display: block; }
  .trap-card .trap-title {
    font-size: 0.95rem; font-weight: 700; color: #e94560; margin-bottom: 8px;
  }
  .trap-card .trap-list { display: flex; gap: 10px; flex-wrap: wrap; }
  .trap-card .trap-item {
    flex: 1; min-width: 200px; padding: 8px 12px;
    background: rgba(233, 69, 96, 0.08); border-radius: 6px;
    border-left: 3px solid #e94560;
  }
  .trap-item .trap-aug-name { font-weight: 600; color: #ff6b7a; }
  .trap-item .trap-level { font-size: 0.75rem; color: #a0a0b0; margin-left: 6px; }
  .trap-item .trap-score {
    font-size: 0.85rem; font-weight: 700;
  }
  .trap-item .trap-detail { font-size: 0.7rem; color: #7a7a8a; margin-top: 2px; }

  /* Misconception score colors */
  .mis-high { color: #f44336; font-weight: 700; }
  .mis-mid { color: #ff9800; font-weight: 600; }
  .mis-low { color: #4a4a5a; }
  tr.trap-row td { border-left: 3px solid #e94560; }
</style>
</head>
<body>
<div class="top-bar">
  <button class="back-btn" id="backBtn" onclick="showChampionList()">← 返回</button>
  <h1>ARAM 符文数据浏览</h1>
  <select id="sourceSel" class="source-select" title="数据源">
    <option value="opgg" {{ 'selected' if default_source == 'opgg' }}>OP.GG</option>
    <option value="aramkit" {{ 'selected' if default_source == 'aramkit' }}>Aramkit</option>
  </select>
  <span class="subtitle" id="headerSub"></span>
</div>

<!-- Champion list view -->
<div id="championView">
  <div class="search-bar">
    <input type="text" id="champSearch" placeholder="搜索英雄名称…" autocomplete="off">
    <span class="count-label" id="champCount"></span>
  </div>
  <div class="champ-grid" id="champGrid"></div>
</div>

<!-- Champion detail view -->
<div id="detailView">
  <div class="detail-bar">
    <label><input type="checkbox" id="level0" checked> Lv.0</label>
    <label><input type="checkbox" id="level1" checked> Lv.1</label>
    <label><input type="checkbox" id="level2" checked> Lv.2</label>
    <span class="filter-group">
      <label>最低表现 <input type="number" id="minPerf" value="0" min="0" max="100" step="0.1"></label>
      <label>最低流行 <input type="number" id="minPop" value="0" min="0" max="100" step="0.1"></label>
    </span>
    <span class="filter-group">
      <label><input type="checkbox" id="trapOnly"> 仅陷阱</label>
      <label>陷阱指数 ≥ <input type="number" id="minMis" value="0" min="0" max="1" step="0.05"></label>
    </span>
    <span class="count-label" id="detailCount" style="margin-left:auto"></span>
  </div>
  <!-- 陷阱警示卡片 -->
  <div class="trap-card" id="trapCard">
    <div class="trap-title">⚠ 陷阱符文 — 很多人选但降低胜率的误解选择</div>
    <div class="trap-list" id="trapList"></div>
  </div>

  <div id="tooltip"></div>
<div class="table-wrap">
    <table id="dataTable">
      <thead>
        <tr>
          <th data-col="augment_name">符文名称 <span class="arrow">▲▼</span></th>
          <th data-col="level">等级 <span class="arrow">▲▼</span></th>
          <th data-col="performance" class="num">表现 <span class="arrow">▲▼</span></th>
          <th data-col="popular" class="num">流行度 <span class="arrow">▲▼</span></th>
          <th data-col="weighted_sum" class="num">综合评分 <span class="arrow">▲▼</span></th>
          <th data-col="misconception" class="num">陷阱指数 <span class="arrow">▲▼</span></th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<script>
let allChampions = [];
let currentAugments = [];
let sortCol = 'weighted_sum';
let sortDir = -1;
const sourceSel = document.getElementById('sourceSel');
let currentSource = sourceSel.value;
const SOURCE_LABELS = { 'opgg': 'OP.GG', 'aramkit': 'Aramkit' };

async function loadChampionList() {
  try {
    const resp = await fetch('/api/champions?source=' + encodeURIComponent(currentSource));
    allChampions = await resp.json();
    renderChampionGrid();
  } catch (err) {
    document.getElementById('champCount').textContent = '加载失败: ' + err.message;
  }
}

function renderChampionGrid() {
  const q = document.getElementById('champSearch').value.toLowerCase();
  const filtered = allChampions.filter(c =>
    c.champion_name_cn.toLowerCase().includes(q) ||
    c.champion_alias.toLowerCase().includes(q) ||
    c.champion_name.toLowerCase().includes(q)
  );
  document.getElementById('champCount').textContent = `共 ${filtered.length} 个英雄`;
  document.getElementById('champGrid').innerHTML = filtered.map(c =>
    `<div class="champ-card" onclick="showChampionDetail('${c.champion_id}','${escHtml(c.champion_name_cn)}')">
      <div class="name">${escHtml(c.champion_name_cn)}</div>
      <div class="alias">${escHtml(c.champion_alias)}</div>
      <div class="count">${c.augment_count} 个符文</div>
    </div>`
  ).join('');
}

async function showChampionDetail(cid, cname) {
  document.getElementById('championView').classList.add('hidden');
  document.getElementById('detailView').classList.add('show');
  document.getElementById('backBtn').classList.add('show');
  const srcLabel = SOURCE_LABELS[currentSource] || currentSource;
  document.getElementById('headerSub').textContent = '— ' + cname + ' (' + srcLabel + ')';
  document.getElementById('detailCount').textContent = '加载中…';
  document.querySelector('#dataTable tbody').innerHTML = '';

  try {
    const resp = await fetch('/api/champions/' + cid + '/augments?source=' + encodeURIComponent(currentSource));
    currentAugments = await resp.json();
    sortCol = 'weighted_sum';
    sortDir = -1;
    renderDetail();
  } catch (err) {
    document.getElementById('detailCount').textContent = '加载失败: ' + err.message;
  }
}

function showChampionList() {
  currentAugments = [];
  document.getElementById('championView').classList.remove('hidden');
  document.getElementById('detailView').classList.remove('show');
  document.getElementById('backBtn').classList.remove('show');
  document.getElementById('headerSub').textContent = '';
  renderChampionGrid();
}

function renderTrapCard() {
  const traps = currentAugments.filter(d => d.is_trap);
  if (traps.length === 0) {
    document.getElementById('trapCard').classList.remove('show');
    return;
  }
  const byMis = [...traps].sort((a, b) => b.misconception - a.misconception).slice(0, 3);
  const labels = {'2': '棱彩', '1': '黄金', '0': '白银'};
  document.getElementById('trapList').innerHTML = byMis.map(d => {
    const cls = d.misconception >= 0.5 ? 'mis-high' : d.misconception >= 0.25 ? 'mis-mid' : 'mis-low';
    const popPct = (d.popular_norm * 100).toFixed(0);
    const perfPct = (d.performance_norm * 100).toFixed(0);
    return `<div class="trap-item">
      <span class="trap-aug-name">${escHtml(d.augment_name)}</span>
      <span class="trap-level">${labels[d.level] || 'Lv'+d.level}</span>
      <div><span class="trap-score ${cls}">${d.misconception.toFixed(3)}</span></div>
      <div class="trap-detail">流行度 ${popPct}% · 表现 ${perfPct}%</div>
    </div>`;
  }).join('');
  document.getElementById('trapCard').classList.add('show');
}

function renderDetail() {
  const showL0 = document.getElementById('level0').checked;
  const showL1 = document.getElementById('level1').checked;
  const showL2 = document.getElementById('level2').checked;
  const minPerf = parseFloat(document.getElementById('minPerf').value) || 0;
  const minPop = parseFloat(document.getElementById('minPop').value) || 0;
  const trapOnly = document.getElementById('trapOnly').checked;
  const minMis = parseFloat(document.getElementById('minMis').value) || 0;
  const allowedLevels = new Set();
  if (showL0) allowedLevels.add('0');
  if (showL1) allowedLevels.add('1');
  if (showL2) allowedLevels.add('2');

  renderTrapCard();

  let filtered = currentAugments.filter(d =>
    allowedLevels.has(d.level) && d.performance >= minPerf && d.popular >= minPop
  );
  if (trapOnly) filtered = filtered.filter(d => d.is_trap);
  if (minMis > 0) filtered = filtered.filter(d => d.misconception >= minMis);
  const sorted = [...filtered].sort((a, b) => {
    let va = a[sortCol], vb = b[sortCol];
    if (typeof va === 'string') return va.localeCompare(vb, 'zh-CN') * sortDir;
    return (va - vb) * sortDir;
  });

  document.querySelector('#dataTable tbody').innerHTML = sorted.map(d => {
    const wsClass = d.weighted_sum >= 0.7 ? 'ws-high' : d.weighted_sum >= 0.4 ? 'ws-mid' : 'ws-low';
    const ws = d.weighted_sum != null ? d.weighted_sum.toFixed(2) : '-';
    const perf = d.performance != null ? d.performance.toFixed(1) : '-';
    const pop = d.popular != null ? d.popular.toFixed(1) : '-';
    const mis = d.misconception != null ? d.misconception.toFixed(3) : '-';
    const misCls = d.misconception >= 0.5 ? 'mis-high' : d.misconception >= 0.25 ? 'mis-mid' : 'mis-low';
    const rowCls = d.is_trap ? 'trap-row' : '';
    return `<tr class="${rowCls}">
      <td><span data-tooltip="${escHtml(d.description || '')}" class="aug-name">${escHtml(d.augment_name)}</span></td>
      <td><span class="level-badge level-${d.level}">${d.level}</span></td>
      <td class="num">${perf}</td>
      <td class="num">${pop}</td>
      <td class="num"><span class="${wsClass}">${ws}</span></td>
      <td class="num"><span class="${misCls}">${mis}</span></td>
    </tr>`;
  }).join('');

  const totalCount = currentAugments.length;
  const suffix = filtered.length !== totalCount ? ` (已筛选，总计 ${totalCount} 条)` : '';
  document.getElementById('detailCount').textContent = `共 ${filtered.length} 条` + suffix;

  document.querySelectorAll('#dataTable th').forEach(th => {
    th.classList.toggle('sorted', th.dataset.col === sortCol);
  });
}

function escHtml(s) {
  const el = document.createElement('span');
  el.textContent = s;
  return el.innerHTML;
}

// --- Tooltip (fixed-position, element-relative, never clipped) ---
const tooltip = document.getElementById('tooltip');
document.querySelector('#dataTable tbody').addEventListener('mouseenter', e => {
  const span = e.target.closest('span[data-tooltip]');
  if (!span) return;
  tooltip.textContent = span.dataset.tooltip;
  tooltip.style.display = 'block';
  const rect = span.getBoundingClientRect();
  const gap = 6;
  let top = rect.top - tooltip.offsetHeight - gap;
  if (top < 0) top = rect.bottom + gap;
  let left = rect.left;
  if (left + tooltip.offsetWidth > window.innerWidth) left = window.innerWidth - tooltip.offsetWidth - gap;
  if (left < gap) left = gap;
  tooltip.style.left = left + 'px';
  tooltip.style.top = top + 'px';
}, true);
document.querySelector('#dataTable tbody').addEventListener('mouseleave', e => {
  const span = e.target.closest('span[data-tooltip]');
  if (!span) return;
  tooltip.style.display = 'none';
}, true);

// --- Event listeners ---
document.getElementById('champSearch').addEventListener('input', renderChampionGrid);

sourceSel.addEventListener('change', () => {
  currentSource = sourceSel.value;
  showChampionList();
  loadChampionList();
});

document.querySelectorAll('#dataTable th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (sortCol === col) { sortDir *= -1; }
    else { sortCol = col; sortDir = col === 'augment_name' ? 1 : -1; }
    renderDetail();
  });
});

document.querySelectorAll('.detail-bar input').forEach(el => {
  el.addEventListener('input', renderDetail);
});

loadChampionList();
</script>
</body>
</html>"""

# ═══════════════════════════════════════════════════════════════════════════
# Flask app
# ═══════════════════════════════════════════════════════════════════════════

app = Flask(__name__)


@app.route("/")
def index():
    return render_template_string(PAGE_HTML, default_source=DEFAULT_SOURCE)


@app.route("/api/champions")
def api_champions():
    source = request.args.get("source", DEFAULT_SOURCE)
    try:
        return jsonify(build_champion_list(source))
    except Exception as e:
        logger.error(f"构建英雄列表失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/champions/<champion_id>/augments")
def api_champion_augments(champion_id: str):
    source = request.args.get("source", DEFAULT_SOURCE)
    try:
        return jsonify(build_champion_augments(champion_id, source))
    except Exception as e:
        logger.error(f"构建英雄 {champion_id} 符文数据失败: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    init_data()
    logger.info("启动 ARAM 符文数据浏览 (独立部署版) at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
