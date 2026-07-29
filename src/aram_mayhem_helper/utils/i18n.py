"""英雄中文名/称号 i18n 工具模块。

为 ``web.py`` 和 ``gui.py`` 提供统一的英雄 i18n 加载与查询接口，
避免重复代码。
"""

import json
import logging

from aram_mayhem_helper.utils.config import config

logger = logging.getLogger(__name__)

_champion_i18n: dict[str, dict] | None = None


def _load() -> dict[str, dict]:
    """从 champions-names-i18n.json 加载数据（内部使用）。"""
    path = config.data_path / "champions-names-i18n.json"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取英雄 i18n 文件失败: {e}")
    return {}


def get_champion_i18n() -> dict[str, dict]:
    """返回 i18n 数据的模块级缓存（懒加载）。"""
    global _champion_i18n
    if _champion_i18n is None:
        _champion_i18n = _load()
    return _champion_i18n


def champion_zh_name(champion_id: str) -> str:
    """根据 numeric champion ID 获取中文名称（如 '安妮'）。

    未找到时返回空字符串。
    """
    info = get_champion_i18n().get(champion_id, {})
    names = info.get("names", {})
    return names.get("zh-CN", "") or info.get("alias", "")


def champion_display_name(champion_id: str) -> str:
    """根据 numeric champion ID 获取中文称号（如 '黑暗之女'）。

    未找到时 fallback 到英文 alias。
    """
    info = get_champion_i18n().get(champion_id, {})
    titles = info.get("titles", {})
    return titles.get("zh-CN", "") or info.get("alias", "")


def champion_alias(champion_id: str) -> str:
    """根据 numeric champion ID 获取英文名称（alias 字段）。

    未找到时返回空字符串。
    """
    info = get_champion_i18n().get(champion_id, {})
    return info.get("alias", "")
