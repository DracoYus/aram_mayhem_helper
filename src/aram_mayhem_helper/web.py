"""ARAM Mayhem Helper 网页应用 — 浏览缓存的所有英雄符文数据。"""

import json
import logging

from flask import Flask, jsonify, render_template_string

from aram_mayhem_helper.utils.config import config
from aram_mayhem_helper.utils.data import augment_tool, champion_augment_data_dict, data
from aram_mayhem_helper.utils.i18n import champion_alias, champion_display_name
from aram_mayhem_helper.utils.norm import add_bayesian_sigmoid_score_attr

logger = logging.getLogger(__name__)

# ── Augment descriptions ───────────────────────────────────────────────────


def _load_augment_descriptions() -> dict[str, dict]:
    path = config.data_path / "aram-mayhem-augments.zh_cn.json"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取符文描述文件失败: {e}")
    return {}


_augment_descriptions: dict[str, dict] = _load_augment_descriptions()


def _augment_description(augment_id: str) -> str:
    """Return cleaned description text for an augment."""
    import re

    info = _augment_descriptions.get(augment_id, {})
    desc = info.get("description", "") or info.get("tooltip", "")
    # Strip pseudo-HTML tags like <scaleAF>, <attention>, <keyword>, etc.
    desc = re.sub(r"<[^>]+>", "", desc)
    return desc


def _build_champion_augments(champion_id: str) -> list[dict]:
    """Build normalized augment data for a single champion.

    Mirrors ``Suggest.__init__``: filters placeholder entries, applies IQR
    min-max normalization + weighted-sum per augment level group.
    """
    champion_name = data.get_champion_name_by_id(champion_id)
    if not champion_name:
        return []

    champ_aug_data = champion_augment_data_dict.get(champion_id)
    if not champ_aug_data:
        return []

    try:
        entries = champ_aug_data.get_champion_augment_data()
    except Exception:
        logger.warning(f"无法读取英雄 {champion_id} 的符文数据，已跳过")
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

        aug_info = augment_tool.get_augment_info(str(item_id))
        if not aug_info:
            continue

        level = aug_info.get("level", "?")
        augment_name = aug_info.get("name", f"ID:{item_id}")

        record = {
            "champion_id": champion_id,
            "champion_name": champion_name,
            "champion_name_cn": champion_display_name(champion_id),
            "champion_alias": champion_alias(champion_id),
            "augment_id": str(item_id),
            "augment_name": augment_name,
            "description": _augment_description(str(item_id)),
            "level": level,
            "performance": perf,
            "popular": pop,
        }
        rows.append(record)
        by_level.setdefault(level, []).append(record)

    for level, level_items in by_level.items():
        try:
            add_bayesian_sigmoid_score_attr(
                level_items,
                perf_attr="performance",
                pop_attr="popular",
                new_attr="weighted_sum",
                tau_factor=config.get("suggest", "shrinkage_tau_factor"),
                sigmoid_steepness=config.get("suggest", "sigmoid_steepness"),
                perf_display_attr="performance_norm",
                pop_display_attr="popular_norm",
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"英雄 {champion_name} 等级 {level} 的符文数据归一化失败: {e}")

    return rows


def _build_champion_list() -> list[dict]:
    """Return a summary list of all champions with cached augment data."""
    champions: list[dict] = []
    for cid in sorted(champion_augment_data_dict.keys(), key=int):
        cname = data.get_champion_name_by_id(cid)
        if not cname:
            continue
        champ_aug_data = champion_augment_data_dict.get(cid)
        count = 0
        if champ_aug_data:
            try:
                entries = champ_aug_data.get_champion_augment_data()
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
      <td><span data-tooltip="${escHtml(d.description || '')}" class="aug-name">${escHtml(d.augment_name)}</span></td>
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

app = Flask(__name__)


@app.route("/")
def index():
    """Serve the main page."""
    return render_template_string(PAGE_HTML)


@app.route("/api/champions")
def api_champions():
    """Return a summary list of all champions with cached augment data."""
    try:
        return jsonify(_build_champion_list())
    except Exception as e:
        logger.error(f"构建英雄列表失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/champions/<champion_id>/augments")
def api_champion_augments(champion_id: str):
    """Return normalized augment data for a specific champion."""
    try:
        return jsonify(_build_champion_augments(champion_id))
    except Exception as e:
        logger.error(f"构建英雄 {champion_id} 符文数据失败: {e}")
        return jsonify({"error": str(e)}), 500
