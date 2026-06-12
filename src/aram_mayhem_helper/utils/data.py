import json
import logging
from pathlib import Path
from typing import Dict

import requests

from aram_mayhem_helper.utils.config import config
from aram_mayhem_helper.utils.text_normalization import normalize_text


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
    def __init__(self, champion_id: str):
        self.champion_id = champion_id
        self.champion_augment_data = None
        self.logger = logging.getLogger(__name__)

    def get_champion_augment_data(self) -> list[dict]:
        """获取英雄符文数据"""
        if not self.champion_augment_data:
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

    def get_augment_id(self, augment_name: str) -> str | None:
        """根据符文名称获取符文ID"""
        normalized_name = normalize_text(augment_name)
        augment_info = self.name_id_dict.get(normalized_name, None)
        if augment_info:
            return augment_info["id"]
        return None

    def get_augment_info(self, augment_id: str) -> dict | None:
        """根据符文名称获取符文ID"""
        return self.id_name_dict.get(augment_id, None)

    def ensure_augment_entry(self, augment_id: str, context: dict | None = None) -> None:
        """确保翻译文件中存在指定符文 ID 的条目，缺失时自动添加占位符。

        name 和 level 均使用占位符填充，需后续手动修改。
        同时更新内存字典并写回翻译文件。

        Args:
            augment_id: 符文 ID（字符串形式）
            context: 可选上下文信息，用于日志输出。
                     可包含 ``champion_id``, ``performance``, ``popular`` 字段。
        """
        if augment_id in self.id_name_dict:
            return

        placeholder_name = f"待翻译 ID:{augment_id}"
        entry = {"name": placeholder_name, "level": "待填写"}

        self.id_name_dict[augment_id] = entry
        self.name_id_dict[placeholder_name] = {"id": augment_id, "level": "待填写"}

        extra = ""
        if context:
            parts = []
            champion_label = context.get("champion_name") or context.get("champion_id")
            if champion_label:
                parts.append(f"英雄={champion_label}")
            if "performance" in context:
                parts.append(
                    f"表现={context['performance']:.1f}"
                    if isinstance(context.get("performance"), (int, float))
                    else f"表现={context['performance']}"
                )
            if "popular" in context:
                parts.append(
                    f"流行={context['popular']:.1f}"
                    if isinstance(context.get("popular"), (int, float))
                    else f"流行={context['popular']}"
                )
            if parts:
                extra = f" ({', '.join(parts)})"
        self.logger.warning(
            f'翻译文件中缺少符文 ID {augment_id} 的翻译{extra}，已自动添加占位符: "{placeholder_name}"，请后续手动修改'
        )
        self._save_trans_file()

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
for champion, champion_info in data.get_all_champion_data().items():
    champion_augment_data_dict[champion_info["key"]] = ChampionAugmentData(champion_info["key"])
augment_tool = AugmentTool()


def _scan_and_fill_missing_translations() -> None:
    """Scan all champion augment data files for untranslated augment IDs.

    Auto-adds placeholder entries for missing IDs, then prints a summary
    of all augment entries that still have placeholder names (both new and
    pre-existing) to assist manual translation.
    """
    logger = logging.getLogger(__name__)
    augment_data_dir = config.data_path / config.get("crawler", "opgg", "aram_augment", "save_directory")
    if not augment_data_dir.exists():
        return

    seen_ids: set[str] = set()
    new_count = 0
    placeholder_contexts: dict[str, dict] = {}

    for file_path in augment_data_dir.iterdir():
        if not file_path.is_file() or not file_path.suffix == ".json":
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            continue

        entries = raw.get("data", [])
        for entry in entries:
            item_id = entry.get("id")
            if item_id is None:
                continue
            aug_id = str(item_id)
            if aug_id in seen_ids:
                continue
            seen_ids.add(aug_id)

            # Record context from the first champion that uses this augment
            if aug_id not in placeholder_contexts:
                champion_id = file_path.stem
                placeholder_contexts[aug_id] = {
                    "champion_id": champion_id,
                    "champion_name": data.get_champion_name_by_id(champion_id),
                    "performance": entry.get("performance", "N/A"),
                    "popular": entry.get("popular", "N/A"),
                }

            if aug_id not in augment_tool.id_name_dict:
                augment_tool.ensure_augment_entry(aug_id, placeholder_contexts[aug_id])
                new_count += 1

    if new_count > 0:
        logger.info(f"翻译文件扫描完成，新增 {new_count} 个占位符条目")

    # Print summary of ALL placeholder entries
    pending = [
        (aug_id, info)
        for aug_id, info in augment_tool.id_name_dict.items()
        if info.get("name", "").startswith("待翻译")
    ]
    if pending:
        logger.info(f"共 {len(pending)} 个符文待翻译，按英雄/流行度/表现排序：")

        def _sort_key(item: tuple[str, dict]) -> tuple[int, str, float, float]:
            aug_id, _info = item
            ctx = placeholder_contexts.get(aug_id)
            if not ctx:
                return (1, "", 0.0, 0.0)
            label = ctx.get("champion_name") or ctx.get("champion_id", "")
            pop = ctx.get("popular", 0)
            perf = ctx.get("performance", 0)
            pop_val = -float(pop) if isinstance(pop, (int, float)) else 0.0
            perf_val = -float(perf) if isinstance(perf, (int, float)) else 0.0
            return (0, label, pop_val, perf_val)

        for aug_id, info in sorted(pending, key=_sort_key):
            ctx = placeholder_contexts.get(aug_id)
            if ctx:
                champion_label = ctx.get("champion_name") or ctx.get("champion_id", "?")
                perf = ctx.get("performance", "N/A")
                pop = ctx.get("popular", "N/A")
                perf_str = f"{perf:.2f}" if isinstance(perf, (int, float)) else perf
                pop_str = f"{pop:.2f}" if isinstance(pop, (int, float)) else pop
                logger.info(
                    f"  ID:{aug_id}  level={info['level']}  "
                    f"示例: 英雄={champion_label}  表现={perf_str}  流行={pop_str}"
                )
            else:
                logger.info(f"  ID:{aug_id}  level={info['level']}")


def reload_data() -> None:
    """Reload champion and augment data from disk after crawling.

    Mutates existing singleton objects in-place so that all modules
    that imported them (gui.py, suggest.py) see updated data without re-importing.

    Also scans all champion augment data for augment IDs that are missing from
    the translation file and auto-adds placeholder entries.
    """
    # Force Data to re-read from disk by clearing its internal caches
    data.champion_data = {}
    data.game_version = None
    data.get_all_champion_data()

    # Rebuild champion_augment_data_dict with fresh ChampionAugmentData instances
    champion_augment_data_dict.clear()
    for champion, champion_info in data.get_all_champion_data().items():
        champion_augment_data_dict[champion_info["key"]] = ChampionAugmentData(champion_info["key"])

    # Scan all champion augment data for missing translations
    _scan_and_fill_missing_translations()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")
    reload_data()
