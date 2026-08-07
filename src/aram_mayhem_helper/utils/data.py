import json
import logging
from pathlib import Path
from typing import Dict

import requests

from aram_mayhem_helper.utils.aramkit import aramkit_resources, convert_augment_records
from aram_mayhem_helper.utils.config import config
from aram_mayhem_helper.utils.text_normalization import normalize_for_lookup


class Data:
    def __init__(self):
        self.game_version: str | None = None
        self.champion_data: Dict[str, dict] = {}
        self.logger = logging.getLogger(__name__)

    def get_all_champion_data(self) -> Dict[str, dict]:
        """获取所有英雄的完整数据"""
        if not self.champion_data:
            champion_data_path = config.data_path / Path(config.get("crawler", "ddragon", "champion", "save_directory"))
            if not champion_data_path.exists():
                return {}
            files = [f for f in champion_data_path.iterdir() if f.is_file()]
            if not files:
                self.logger.error(f"没有找到任何英雄数据文件在: {champion_data_path}")
                return {}
            latest_file = max(files, key=lambda f: f.name)
            try:
                with open(latest_file, "r", encoding="utf-8") as f:
                    self.champion_data = json.load(f)["data"]

            except Exception as e:
                self.logger.error(f"读取英雄ID时发生错误: {str(e)}")
        return self.champion_data

    def get_latest_ddragon_version(self) -> str:
        url = "https://ddragon.leagueoflegends.com/api/versions.json"
        response = requests.get(url)
        versions = response.json()
        return versions[0]  # 第一个元素是最新版本

    def get_game_version(self) -> str | None:
        """获取游戏版本"""
        if not self.game_version:
            try:
                url = "https://ddragon.leagueoflegends.com/api/versions.json"
                response = requests.get(url)
                versions = response.json()
                self.game_version = versions[0]  # 第一个元素是最新版本
            except Exception as e:
                self.logger.error(f"获取游戏版本时发生错误: {str(e)}")
                self.game_version = None
        return self.game_version

    def get_champion_id_by_name(self, champion_name: str) -> str | None:
        """根据英雄名称获取英雄 ID"""
        champion_data = self.get_all_champion_data()
        for champ_id, champ_info in champion_data.items():
            if champ_info["id"].lower() == champion_name.lower():
                return champ_info["key"]
        self.logger.warning(f"未找到英雄名称 '{champion_name}' 对应的 ID")
        return None

    def get_champion_name_by_id(self, champion_id: str) -> str | None:
        """根据英雄 ID（key）获取英雄名称"""
        champion_data = self.get_all_champion_data()
        for champ_info in champion_data.values():
            if champ_info["key"] == champion_id:
                return champ_info["name"]
        self.logger.warning(f"未找到英雄 ID '{champion_id}' 对应的名称")
        return None


class ChampionAugmentData:
    def __init__(self, champion_id: str, source: str = "opgg"):
        self.champion_id = champion_id
        self.source = source
        self.champion_augment_data = None
        self.logger = logging.getLogger(__name__)

    def get_champion_augment_data(self) -> list[dict]:
        """获取英雄符文数据（按数据源分发：opgg / aramkit）"""
        if not self.champion_augment_data:
            if self.source == "aramkit":
                champion_data_path = (
                    config.data_path
                    / Path(config.get("crawler", "aramkit", "aram_augment", "save_directory"))
                    / config.get("crawler", "aramkit", "aram_augment", "dataset", default="all")
                    / f"{self.champion_id}.json"
                )
                try:
                    with open(champion_data_path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                except FileNotFoundError:
                    self.logger.error(f"未找到英雄符文数据文件: {champion_data_path}")
                    raise
                except json.JSONDecodeError as e:
                    self.logger.error(f"英雄符文数据文件格式错误: {champion_data_path}, 错误: {str(e)}")
                    raise
                except Exception as e:
                    self.logger.error(f"读取英雄符文数据文件时发生错误: {champion_data_path}, 错误: {str(e)}")
                    raise
                augments = raw_data.get("augments", {}).get("all", [])
                self.champion_augment_data = convert_augment_records(augments)
            else:
                champion_data_path = (
                    config.data_path
                    / Path(config.get("crawler", "opgg", "aram_augment", "save_directory"))
                    / f"{self.champion_id}.json"
                )
                try:
                    with open(champion_data_path, "r", encoding="utf-8") as f:
                        self.champion_augment_data = json.load(f)
                except FileNotFoundError:
                    self.logger.error(f"未找到英雄符文数据文件: {champion_data_path}")
                    raise
                except json.JSONDecodeError as e:
                    self.logger.error(f"英雄符文数据文件格式错误: {champion_data_path}, 错误: {str(e)}")
                    raise
                except Exception as e:
                    self.logger.error(f"读取英雄符文数据文件时发生错误: {champion_data_path}, 错误: {str(e)}")
                    raise
        if self.source == "aramkit":
            return self.champion_augment_data
        data = self.champion_augment_data.get("data")
        if data is None:
            self.logger.warning(f"英雄符文数据文件缺少 'data' 字段: champion_id={self.champion_id}")
            return []
        return data


class AugmentTool:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.id_name_dict = {}
        self.name_id_dict = {}
        self._name_norm_dict: dict[str, str] = {}  # 归一化名 → 原始名映射
        trans_file = config.data_path / "augment_trans.json"
        if trans_file.exists():
            try:
                with open(trans_file, "r", encoding="utf-8") as f:
                    self.id_name_dict = json.load(f)
            except json.JSONDecodeError as e:
                self.logger.error(f"翻译文件格式错误: {trans_file}, 错误: {str(e)}")
                raise
            except Exception as e:
                self.logger.error(f"读取翻译文件时发生错误: {trans_file}, 错误: {str(e)}")
                raise
        else:
            self.logger.warning(f"未找到翻译文件: {trans_file}")
        for aug_id, info in self.id_name_dict.items():
            name = info.get("name")
            level = info.get("level")
            if not name:
                self.logger.warning(f"翻译文件中符文 ID {aug_id} 缺少 'name' 字段，已跳过")
                continue
            if level is None:
                self.logger.warning(f"翻译文件中符文 ID {aug_id}({name}) 缺少 'level' 字段，已跳过")
                continue
            self.name_id_dict[name] = {"id": aug_id, "level": level}
            # 构建归一化名 → 原始名的索引
            norm = normalize_for_lookup(name)
            if norm not in self._name_norm_dict:
                self._name_norm_dict[norm] = name

    def get_augment_id(self, augment_name: str) -> str | None:
        """根据符文名称获取符文ID，支持空格/连字符的 OCR 变体容错匹配."""
        # 先精确匹配（快路径）
        augment_info = self.name_id_dict.get(augment_name)
        if augment_info:
            return augment_info["id"]

        # 归一化匹配：消除 OCR 产出的空格、连字符差异
        input_norm = normalize_for_lookup(augment_name)
        original_name = self._name_norm_dict.get(input_norm)
        if original_name is None:
            return None
        augment_info = self.name_id_dict.get(original_name)
        if augment_info:
            return augment_info["id"]
        return None

    def get_augment_info(self, augment_id: str) -> dict | None:
        """根据符文名称获取符文ID"""
        return self.id_name_dict.get(augment_id, None)

    def _save_trans_file(self) -> None:
        """将当前 in-memory 翻译数据按 ID 排序后写回 augment_trans.json。"""
        trans_file = config.data_path / "augment_trans.json"
        try:
            sorted_dict = {k: self.id_name_dict[k] for k in sorted(self.id_name_dict, key=int)}
            with open(trans_file, "w", encoding="utf-8") as f:
                json.dump(sorted_dict, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.logger.error(f"保存翻译文件时发生错误: {trans_file}, 错误: {str(e)}")


data = Data()
champion_augment_data_dict = {}
aramkit_champion_augment_data_dict = {}
for champion, champion_info in data.get_all_champion_data().items():
    champion_augment_data_dict[champion_info["key"]] = ChampionAugmentData(champion_info["key"])
    aramkit_champion_augment_data_dict[champion_info["key"]] = ChampionAugmentData(
        champion_info["key"], source="aramkit"
    )
augment_tool = AugmentTool()


def get_default_source() -> str:
    """返回配置的数据源，非法值回退 "opgg"。"""
    src = config.get("data_source", "source", default="opgg")
    return src if src in ("opgg", "aramkit") else "opgg"


def get_champion_augment_data(champion_id: str, source: str | None = None) -> ChampionAugmentData | None:
    """按数据源（默认取配置）返回英雄符文数据对象。"""
    source = source or get_default_source()
    data_dict = champion_augment_data_dict if source == "opgg" else aramkit_champion_augment_data_dict
    return data_dict.get(champion_id)


def get_champion_augment_data_dict(source: str | None = None) -> dict[str, ChampionAugmentData]:
    """返回对应数据源的 {champion_key: ChampionAugmentData} 字典。"""
    source = source or get_default_source()
    return champion_augment_data_dict if source == "opgg" else aramkit_champion_augment_data_dict


def get_augment_info_for_source(source: str, augment_id: str) -> dict | None:
    """根据数据源获取符文信息：翻译表优先，aramkit 缺失时回退其资源文件。"""
    info = augment_tool.get_augment_info(augment_id)
    if info is None and source == "aramkit":
        info = aramkit_resources.get_augment_info(augment_id)
    return info


def get_augment_id_for_source(source: str, augment_name: str) -> str | None:
    """根据数据源将符文名称反查为 ID：翻译表优先，aramkit 缺失时回退其资源文件。"""
    augment_id = augment_tool.get_augment_id(augment_name)
    if augment_id is None and source == "aramkit":
        augment_id = aramkit_resources.get_augment_id(augment_name)
    return augment_id


def reload_data() -> None:
    """Reload champion and augment data from disk after crawling.

    Mutates existing singleton objects in-place so that all modules
    that imported them (gui.py, suggest.py) see updated data without re-importing.
    """
    # Force Data to re-read from disk by clearing its internal caches
    data.champion_data = {}
    data.game_version = None
    data.get_all_champion_data()

    # Rebuild champion_augment_data_dict with fresh ChampionAugmentData instances
    champion_augment_data_dict.clear()
    aramkit_champion_augment_data_dict.clear()
    for champion, champion_info in data.get_all_champion_data().items():
        champion_augment_data_dict[champion_info["key"]] = ChampionAugmentData(champion_info["key"])
        aramkit_champion_augment_data_dict[champion_info["key"]] = ChampionAugmentData(
            champion_info["key"], source="aramkit"
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")
    reload_data()
