"""数据层：GameData 仓储门面 + AugmentLookup 翻译表查询。"""

import json
import logging
from pathlib import Path

from aram_mayhem_helper.utils.aramkit import AramkitResources, convert_augment_records
from aram_mayhem_helper.utils.config import AppConfig, get_config
from aram_mayhem_helper.utils.text_normalization import normalize_for_lookup


class AugmentLookup:
    """翻译表（augment_trans.json）加载与名称↔ID 查询。

    懒加载：首次查询时读文件并构建索引；``reload()`` 清空缓存后重新读取
    （修复旧实现 reload_data 不重建翻译表的缺陷）。
    """

    def __init__(self, trans_file: Path, aramkit_resources: AramkitResources | None = None) -> None:
        self.logger = logging.getLogger(__name__)
        self._trans_file = trans_file
        self._aramkit_resources = aramkit_resources
        self.id_name_dict: dict[str, dict] = {}
        self.name_id_dict: dict[str, dict] = {}
        self._name_norm_dict: dict[str, str] = {}  # 归一化名 → 原始名映射

    def _load(self) -> None:
        if self.id_name_dict:
            return
        if self._trans_file.exists():
            try:
                with open(self._trans_file, "r", encoding="utf-8") as f:
                    self.id_name_dict = json.load(f)
            except json.JSONDecodeError as e:
                self.logger.error(f"翻译文件格式错误: {self._trans_file}, 错误: {str(e)}")
                raise
            except Exception as e:
                self.logger.error(f"读取翻译文件时发生错误: {self._trans_file}, 错误: {str(e)}")
                raise
        else:
            self.logger.warning(f"未找到翻译文件: {self._trans_file}")
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

    def reload(self) -> None:
        """清空缓存并立即重新读取翻译表。"""
        self.id_name_dict = {}
        self.name_id_dict = {}
        self._name_norm_dict = {}
        self._load()

    def get_augment_id(self, augment_name: str) -> str | None:
        """根据符文名称获取符文ID，支持空格/连字符的 OCR 变体容错匹配."""
        self._load()
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
        """根据符文 ID 获取翻译表条目。"""
        self._load()
        return self.id_name_dict.get(augment_id, None)


class GameData:
    """游戏数据仓储门面：英雄元数据、符文条目（按 (champion, source) 缓存）、源感知查找。

    构造仅保存配置路径，不产生任何文件读取（无导入期副作用）；
    ``reload()`` 清空全部缓存（含翻译表与 aramkit 资源）。
    """

    def __init__(self, config: AppConfig) -> None:
        self.logger = logging.getLogger(__name__)
        self._config = config
        self._champion_data: dict[str, dict] | None = None
        self._entries_cache: dict[tuple[str, str], list[dict]] = {}
        self._lookup: AugmentLookup | None = None
        self._resources: AramkitResources | None = None

    # ── 英雄元数据 ──────────────────────────────────────────────────────

    def _champions(self) -> dict[str, dict]:
        if self._champion_data is None:
            path = self._config.champion_dir
            if not path.exists():
                self._champion_data = {}
                return self._champion_data
            files = [f for f in path.iterdir() if f.is_file()]
            if not files:
                self.logger.error(f"没有找到任何英雄数据文件在: {path}")
                self._champion_data = {}
                return self._champion_data
            latest_file = max(files, key=lambda f: f.name)
            try:
                with open(latest_file, "r", encoding="utf-8") as f:
                    self._champion_data = json.load(f)["data"]
            except Exception as e:
                self.logger.error(f"读取英雄ID时发生错误: {str(e)}")
                self._champion_data = {}
        return self._champion_data

    def champion_ids(self) -> list[str]:
        """全部英雄 ID（按整数升序）。"""
        return sorted((info["key"] for info in self._champions().values()), key=int)

    def champion_id_by_name(self, champion_name: str) -> str | None:
        """根据英雄名称获取英雄 ID（不区分大小写）。"""
        for champ_id, champ_info in self._champions().items():
            if champ_info["id"].lower() == champion_name.lower():
                return champ_info["key"]
        self.logger.warning(f"未找到英雄名称 '{champion_name}' 对应的 ID")
        return None

    def champion_name(self, champion_id: str) -> str | None:
        """根据英雄 ID（key）获取英雄名称。"""
        for champ_info in self._champions().values():
            if champ_info["key"] == champion_id:
                return champ_info["name"]
        self.logger.warning(f"未找到英雄 ID '{champion_id}' 对应的名称")
        return None

    # ── 符文条目 ────────────────────────────────────────────────────────

    def augment_entries(self, champion_id: str, source: str | None = None) -> list[dict] | None:
        """返回该英雄的引擎标准符文条目。

        Args:
            champion_id: 英雄 ID
            source: 数据源（"opgg"/"aramkit"），None 取配置默认

        Returns:
            条目列表；英雄未知时返回 None；文件缺失/损坏时照旧抛出
            ``FileNotFoundError``/``JSONDecodeError``
        """
        source = source or self.default_source()
        if self.champion_name(champion_id) is None:
            return None
        cache_key = (champion_id, source)
        if cache_key in self._entries_cache:
            return self._entries_cache[cache_key]
        if source == "aramkit":
            champion_data_path = self._config.aramkit_augment_dir / f"{champion_id}.json"
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
            entries = convert_augment_records(raw_data.get("augments", {}).get("all", []))
        else:
            champion_data_path = self._config.opgg_augment_dir / f"{champion_id}.json"
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
            data = raw_data.get("data")
            if data is None:
                self.logger.warning(f"英雄符文数据文件缺少 'data' 字段: champion_id={champion_id}")
                entries = []
            else:
                entries = data
        self._entries_cache[cache_key] = entries
        return entries

    def augment_entries_all(self, source: str | None = None) -> dict[str, list[dict] | None]:
        """全部英雄的条目（懒加载，供 web 列表构建）。"""
        source = source or self.default_source()
        return {cid: self.augment_entries(cid, source) for cid in self.champion_ids()}

    # ── 源感知符文查找 ──────────────────────────────────────────────────

    def _lookup_impl(self) -> AugmentLookup:
        if self._lookup is None:
            self._lookup = AugmentLookup(self._config.trans_file, self._resources_impl())
        return self._lookup

    def _resources_impl(self) -> AramkitResources:
        if self._resources is None:
            self._resources = AramkitResources(self._config.aramkit_resources_dir)
        return self._resources

    def augment_info(self, augment_id: str, source: str | None = None) -> dict | None:
        """根据数据源获取符文信息：翻译表优先，aramkit 缺失时回退其资源文件。"""
        source = source or self.default_source()
        info = self._lookup_impl().get_augment_info(augment_id)
        if info is None and source == "aramkit":
            info = self._resources_impl().get_augment_info(augment_id)
        return info

    def augment_id(self, augment_name: str, source: str | None = None) -> str | None:
        """根据数据源将符文名称反查为 ID：翻译表优先，aramkit 缺失时回退其资源文件。"""
        source = source or self.default_source()
        augment_id = self._lookup_impl().get_augment_id(augment_name)
        if augment_id is None and source == "aramkit":
            augment_id = self._resources_impl().get_augment_id(augment_name)
        return augment_id

    def default_source(self) -> str:
        """配置默认数据源。"""
        return self._config.data_source.source

    # ── 刷新 ────────────────────────────────────────────────────────────

    def reload(self) -> None:
        """清空全部缓存（英雄数据、符文条目、翻译表、aramkit 资源），下次访问重新读取。"""
        self._champion_data = None
        self._entries_cache.clear()
        self._lookup_impl().reload()
        self._resources_impl().reload()


_game_data_singleton: GameData | None = None


def get_game_data() -> GameData:
    """懒加载 GameData 单例（替代旧导入期构建全部数据对象的副作用）。"""
    global _game_data_singleton
    if _game_data_singleton is None:
        _game_data_singleton = GameData(get_config())
    return _game_data_singleton
