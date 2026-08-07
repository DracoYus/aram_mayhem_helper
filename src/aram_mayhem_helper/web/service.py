"""web 服务层：英雄 i18n 名称、符文描述与列表/明细构建（HTTP 关注点）。"""

import json
import logging
import re
from functools import lru_cache
from typing import Any

from aram_mayhem_helper.algorithm.pipeline import build_scored_groups
from aram_mayhem_helper.utils.config import get_config
from aram_mayhem_helper.utils.data import GameData

logger = logging.getLogger(__name__)


# ── i18n 名称与符文描述（懒加载 + 缓存）────────────────────────────────────


@lru_cache(maxsize=1)
def _load_champion_i18n() -> dict[str, dict[str, Any]]:
    path = get_config().i18n_file
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data: dict[str, dict[str, Any]] = json.load(f)
                return data
        except Exception as e:
            logger.warning(f"读取英雄 i18n 文件失败: {e}")
    return {}


@lru_cache(maxsize=1)
def _load_augment_descriptions() -> dict[str, dict[str, Any]]:
    path = get_config().augment_desc_file
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data: dict[str, dict[str, Any]] = json.load(f)
                return data
        except Exception as e:
            logger.warning(f"读取符文描述文件失败: {e}")
    return {}


def champion_display_name(champion_id: str) -> str:
    """返回英雄中文称号。"""
    info = _load_champion_i18n().get(champion_id, {})
    titles = info.get("titles", {})
    return str(titles.get("zh-CN", "") or info.get("alias", ""))


def champion_alias(champion_id: str) -> str:
    """返回英文别名（搜索/识别用）。"""
    info = _load_champion_i18n().get(champion_id, {})
    return str(info.get("alias", ""))


def augment_description(augment_id: str) -> str:
    """返回清理过伪 HTML 标签的符文描述。"""
    info = _load_augment_descriptions().get(augment_id, {})
    desc = str(info.get("description", "") or info.get("tooltip", ""))
    # Strip pseudo-HTML tags like <scaleAF>, <attention>, <keyword>, etc.
    desc = re.sub(r"<[^>]+>", "", desc)
    return desc


# ── 列表/明细构建 ─────────────────────────────────────────────────────────


def build_champion_augments(game_data: GameData, champion_id: str, source: str | None = None) -> list[dict[str, Any]]:
    """构建单个英雄的归一化符文数据（JSON 记录形状与排序保持历史行为）。

    Args:
        game_data: 数据仓储
        champion_id: 英雄ID
        source: 数据源（"opgg"/"aramkit"），None 时取配置默认
    """
    source = source or game_data.default_source()
    champion_name = game_data.champion_name(champion_id)
    if not champion_name:
        return []

    try:
        entries = game_data.augment_entries(champion_id, source)
    except Exception:
        logger.warning(f"无法读取英雄 {champion_id} 的符文数据，已跳过")
        return []
    if entries is None:
        return []

    config = get_config()
    build_scored_groups(
        entries,
        lookup=lambda augment_id: game_data.augment_info(augment_id, source),
        tau_factor=config.suggest.shrinkage_tau_factor,
        sigmoid_steepness=config.suggest.sigmoid_steepness,
        assign_rank=False,
        champion_id=champion_id,
        logger=logger,
    )

    # 显示尺度统一：aramkit 原生 0~1（winRate/pickRate），×100 与 OP.GG 的 0-100 一致
    display_scale = 100 if source == "aramkit" else 1
    rows: list[dict[str, Any]] = []
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
        # 未通过过滤/打分（lookup miss、打分失败组）→ 不返回
        if "weighted_sum" not in entry:
            continue
        rows.append(
            {
                "champion_id": champion_id,
                "champion_name": champion_name,
                "champion_name_cn": champion_display_name(champion_id),
                "champion_alias": champion_alias(champion_id),
                "augment_id": str(item_id),
                "augment_name": entry["name"],
                "description": augment_description(str(item_id)),
                "level": entry["level"],
                "performance": perf,
                "popular": pop,
                "performance_display": perf * display_scale,
                "popular_display": pop * display_scale,
                "performance_unit": entry["performance_unit"],
                "popular_unit": entry["popular_unit"],
                "weighted_sum": entry["weighted_sum"],
                "performance_norm": entry["performance_norm"],
                "popular_norm": entry["popular_norm"],
            }
        )
    return rows


def build_champion_list(game_data: GameData, source: str | None = None) -> list[dict[str, Any]]:
    """返回所有已缓存符文数据的英雄摘要列表。"""
    source = source or game_data.default_source()
    champions: list[dict[str, Any]] = []
    for cid in game_data.champion_ids():
        cname = game_data.champion_name(cid)
        if not cname:
            continue
        count = 0
        try:
            entries = game_data.augment_entries(cid, source)
            if entries:
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
