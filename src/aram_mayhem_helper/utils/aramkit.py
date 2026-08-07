"""aramkit.com 数据适配模块：将 aramkit 原始数据转换为引擎标准记录，并提供资源文件回退查找。"""

import json
import logging
from pathlib import Path
from typing import Dict

from aram_mayhem_helper.utils.config import config
from aram_mayhem_helper.utils.text_normalization import normalize_text

# aramkit rarity → 引擎 level（2=棱彩, 1=黄金, 0=白银）
RARITY_TO_LEVEL = {"prismatic": "2", "gold": "1", "silver": "0"}


def convert_augment_records(augment_list: list[dict]) -> list[dict]:
    """将 aramkit augment 记录转换为引擎标准记录。

    不做字段同构：performance/popular 直接取 aramkit 原生 0~1 小数值
    （winRate/pickRate），不换算成 OP.GG 的 0~100 尺度；
    两源在引擎归一化层统一缩放到 0~1 后再参与打分。

    Args:
        augment_list: aramkit champion-details 中 ``augments.all`` 的记录列表

    Returns:
        引擎标准记录列表（字段含 id/performance/popular 及保留的原始字段），
        缺少 id/winRate/pickRate 的记录被跳过
    """
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
        # 保留原始统计字段供后续使用
        for key in ("sampleCount", "rank", "stageAgnostic", "availableStages"):
            if key in item:
                record[key] = item[key]
        converted.append(record)
    return converted


def _version_sort_key(version: str) -> tuple:
    """版本目录名排序键：按游戏版本号（major.minor）+ 资源哈希排序取最新。"""
    parts = version.split("-")
    major_minor = parts[0].split(".")
    return (int(major_minor[0]), int(major_minor[1]), parts[1] if len(parts) > 1 else "")


class AramkitResources:
    """懒加载 aramkit resources 文件，提供翻译表缺失条目的回退查找。"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.resources_directory = config.data_path / Path(
            config.get("crawler", "aramkit", "resources", "save_directory")
        )
        self.augment_id_name_dict: Dict[str, dict] = {}
        self.augment_name_id_dict: Dict[str, dict] = {}

    def _load(self) -> None:
        """加载最新版本子目录下的 augments.json。"""
        if self.augment_id_name_dict:
            return
        if not self.resources_directory.exists():
            return
        version_dirs = [d for d in self.resources_directory.iterdir() if d.is_dir()]
        if not version_dirs:
            return
        latest_dir = max(version_dirs, key=lambda d: _version_sort_key(d.name))

        augments_file = latest_dir / "augments.json"
        if augments_file.exists():
            try:
                with open(augments_file, "r", encoding="utf-8") as f:
                    raw_augments = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.logger.error(f"读取 aramkit augments 资源文件失败: {augments_file}, 错误: {str(e)}")
                raw_augments = {}
            for aug_id, info in raw_augments.items():
                name = info.get("name")
                if not name:
                    continue
                level = RARITY_TO_LEVEL.get(info.get("rarity"), "0")
                entry = {"name": name, "level": level}
                self.augment_id_name_dict[aug_id] = entry
                self.augment_name_id_dict[normalize_text(name)] = {"id": aug_id, "level": level}

    def get_augment_info(self, augment_id: str) -> dict | None:
        """根据符文 ID 获取 {"name", "level"}，未找到时返回 None。"""
        self._load()
        return self.augment_id_name_dict.get(augment_id)

    def get_augment_id(self, augment_name: str) -> str | None:
        """根据符文名称反查 ID（归一化后匹配），未找到时返回 None。"""
        self._load()
        normalized_name = normalize_text(augment_name)
        augment_info = self.augment_name_id_dict.get(normalized_name)
        if augment_info:
            return augment_info["id"]
        return None


aramkit_resources = AramkitResources()
