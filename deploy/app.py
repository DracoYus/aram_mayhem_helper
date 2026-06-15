"""ARAM 符文数据浏览 — 独立部署版。

零依赖 aram_mayhem_helper 包，仅需 flask + numpy。
启动: python app.py
"""

import json
import logging
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, render_template_string

# ── Paths (relative to this file) ──────────────────────────────────────────
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
CHAMPIONS_DIR = DATA_DIR / "ddragon" / "champions"
AUGMENTS_DIR = DATA_DIR / "opgg" / "aram_augments"
TRANS_FILE = DATA_DIR / "augment_trans.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Normalization (inlined from aram_mayhem_helper.utils.norm)
# ═══════════════════════════════════════════════════════════════════════════


def _get_normal_min_max(values: list) -> dict:
    arr = np.array(values)
    q1 = np.percentile(arr, 25)
    q3 = np.percentile(arr, 75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    normal_mask = (arr >= lower_bound) & (arr <= upper_bound)
    normal_values = arr[normal_mask]
    if len(normal_values) == 0:
        normal_values = arr
    return {"min": normal_values.min(), "max": normal_values.max()}


def _min_max_normalize(values: list, min_max_norm: bool) -> dict:
    if min_max_norm:
        norm_params = _get_normal_min_max(values)
        min_val = norm_params["min"]
        max_val = norm_params["max"]
    else:
        min_val = min(values)
        max_val = max(values)
    if max_val == min_val:
        return {"normalize_func": lambda x: 0.0}
    return {"normalize_func": lambda x: (x - min_val) / (max_val - min_val)}


def add_normalized_attr(
    data_list: list, src_attr: str, new_attr: str, normalize_type: str = "min-max", min_max_norm: bool = True
) -> None:
    src_values = [item[src_attr] for item in data_list]
    norm_info = _min_max_normalize(src_values, min_max_norm)
    for item in data_list:
        item[new_attr] = round(norm_info["normalize_func"](item[src_attr]), 4)


def add_weighted_sum_attr(
    data_list: list, attr1: str, attr2: str, weight1: float, weight2: float, new_attr: str
) -> None:
    for item in data_list:
        item[new_attr] = round(item[attr1] * weight1 + item[attr2] * weight2, 2)


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
AUGMENT_TRANS: dict[str, dict] = {}


def init_data() -> None:
    """Pre-load champion names and augment translations into memory."""
    global CHAMPION_NAMES, AUGMENT_TRANS
    CHAMPION_NAMES = _build_champion_id_name_map()
    AUGMENT_TRANS = _load_augment_trans()
    logger.info(f"已加载 {len(CHAMPION_NAMES)} 个英雄, {len(AUGMENT_TRANS)} 条符文翻译")


def get_champion_name(cid: str) -> str | None:
    return CHAMPION_NAMES.get(cid)


def get_augment_info(aug_id: str) -> dict | None:
    return AUGMENT_TRANS.get(aug_id)


# ═══════════════════════════════════════════════════════════════════════════
# Data aggregation
# ═══════════════════════════════════════════════════════════════════════════


def _list_cached_champion_ids() -> list[str]:
    """Return sorted list of champion IDs that have cached augment data."""
    if not AUGMENTS_DIR.exists():
        return []
    return sorted(
        [f.stem for f in AUGMENTS_DIR.iterdir() if f.suffix == ".json"],
        key=int,
    )


def build_champion_list() -> list[dict]:
    champions: list[dict] = []
    for cid in _list_cached_champion_ids():
        cname = get_champion_name(cid)
        if not cname:
            continue
        aug_file = AUGMENTS_DIR / f"{cid}.json"
        count = 0
        try:
            entries = _load_json(aug_file).get("data", [])
            count = sum(
                1
                for e in entries
                if e.get("performance") is not None
                and e.get("popular") is not None
                and not (e.get("performance") == 170 and e.get("popular") == 0)
                and e.get("id") is not None
            )
        except Exception:
            count = 0
        champions.append({"champion_id": cid, "champion_name": cname, "augment_count": count})
    return champions


def build_champion_augments(champion_id: str) -> list[dict]:
    cname = get_champion_name(champion_id)
    if not cname:
        return []

    aug_file = AUGMENTS_DIR / f"{champion_id}.json"
    try:
        entries = _load_json(aug_file).get("data", [])
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
        if perf == 170 and pop == 0:
            continue

        item_id = entry.get("id")
        if item_id is None:
            continue

        aug_info = get_augment_info(str(item_id))
        if not aug_info:
            continue

        level = aug_info.get("level", "?")
        augment_name = aug_info.get("name", f"ID:{item_id}")

        record = {
            "champion_id": champion_id,
            "champion_name": cname,
            "augment_id": str(item_id),
            "augment_name": augment_name,
            "level": level,
            "performance": perf,
            "popular": pop,
        }
        rows.append(record)
        by_level.setdefault(level, []).append(record)

    for level, level_items in by_level.items():
        try:
            add_normalized_attr(level_items, "performance", "performance_norm", "min-max", True)
            add_normalized_attr(level_items, "popular", "popular_norm", "min-max", False)
            add_weighted_sum_attr(level_items, "performance_norm", "popular_norm", 0.7, 0.3, "weighted_sum")
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"英雄 {cname} 等级 {level} 归一化失败: {e}")

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
</style>
</head>
<body>
<div class="top-bar">
  <button class="back-btn" id="backBtn" onclick="showChampionList()">← 返回</button>
  <h1>ARAM 符文数据浏览</h1>
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
    <span class="count-label" id="detailCount" style="margin-left:auto"></span>
  </div>
  <div class="table-wrap">
    <table id="dataTable">
      <thead>
        <tr>
          <th data-col="augment_name">符文名称 <span class="arrow">▲▼</span></th>
          <th data-col="level">等级 <span class="arrow">▲▼</span></th>
          <th data-col="performance" class="num">表现 <span class="arrow">▲▼</span></th>
          <th data-col="popular" class="num">流行度 <span class="arrow">▲▼</span></th>
          <th data-col="weighted_sum" class="num">综合评分 <span class="arrow">▲▼</span></th>
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

async function loadChampionList() {
  try {
    const resp = await fetch('/api/champions');
    allChampions = await resp.json();
    renderChampionGrid();
  } catch (err) {
    document.getElementById('champCount').textContent = '加载失败: ' + err.message;
  }
}

function renderChampionGrid() {
  const q = document.getElementById('champSearch').value.toLowerCase();
  const filtered = allChampions.filter(c => c.champion_name.toLowerCase().includes(q));
  document.getElementById('champCount').textContent = `共 ${filtered.length} 个英雄`;
  document.getElementById('champGrid').innerHTML = filtered.map(c =>
    `<div class="champ-card" onclick="showChampionDetail('${c.champion_id}','${escHtml(c.champion_name)}')">
      <div class="name">${escHtml(c.champion_name)}</div>
      <div class="count">${c.augment_count} 个符文</div>
    </div>`
  ).join('');
}

async function showChampionDetail(cid, cname) {
  document.getElementById('championView').classList.add('hidden');
  document.getElementById('detailView').classList.add('show');
  document.getElementById('backBtn').classList.add('show');
  document.getElementById('headerSub').textContent = '— ' + cname;
  document.getElementById('detailCount').textContent = '加载中…';
  document.querySelector('#dataTable tbody').innerHTML = '';

  try {
    const resp = await fetch('/api/champions/' + cid + '/augments');
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

function renderDetail() {
  const showL0 = document.getElementById('level0').checked;
  const showL1 = document.getElementById('level1').checked;
  const showL2 = document.getElementById('level2').checked;
  const minPerf = parseFloat(document.getElementById('minPerf').value) || 0;
  const minPop = parseFloat(document.getElementById('minPop').value) || 0;
  const allowedLevels = new Set();
  if (showL0) allowedLevels.add('0');
  if (showL1) allowedLevels.add('1');
  if (showL2) allowedLevels.add('2');

  const filtered = currentAugments.filter(d =>
    allowedLevels.has(d.level) && d.performance >= minPerf && d.popular >= minPop
  );
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
    return `<tr>
      <td>${escHtml(d.augment_name)}</td>
      <td><span class="level-badge level-${d.level}">${d.level}</span></td>
      <td class="num">${perf}</td>
      <td class="num">${pop}</td>
      <td class="num"><span class="${wsClass}">${ws}</span></td>
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

// --- Event listeners ---
document.getElementById('champSearch').addEventListener('input', renderChampionGrid);

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
    return render_template_string(PAGE_HTML)


@app.route("/api/champions")
def api_champions():
    try:
        return jsonify(build_champion_list())
    except Exception as e:
        logger.error(f"构建英雄列表失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/champions/<champion_id>/augments")
def api_champion_augments(champion_id: str):
    try:
        return jsonify(build_champion_augments(champion_id))
    except Exception as e:
        logger.error(f"构建英雄 {champion_id} 符文数据失败: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    init_data()
    logger.info("启动 ARAM 符文数据浏览 (独立部署版) at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
