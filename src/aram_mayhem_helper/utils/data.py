"""数据层：GameData 仓储门面 + AugmentLookup 翻译表查询。"""

import json
import logging
from pathlib import Path
from typing import Any

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
        self.id_name_dict: dict[str, dict[str, Any]] = {}
        self.name_id_dict: dict[str, dict[str, Any]] = {}
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
            return str(augment_info["id"])

        # 归一化匹配：消除 OCR 产出的空格、连字符差异
        input_norm = normalize_for_lookup(augment_name)
        original_name = self._name_norm_dict.get(input_norm)
        if original_name is None:
            return None
        augment_info = self.name_id_dict.get(original_name)
        if augment_info:
            return str(augment_info["id"])
        return None

    def get_augment_info(self, augment_id: str) -> dict[str, Any] | None:
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
        self._champion_data: dict[str, dict[str, Any]] | None = None
        self._champion_name_by_key: dict[str, str] | None = None  # key → 名称
        self._champion_key_by_name: dict[str, str] | None = None  # lower(name) → key
        self._entries_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._lookup: AugmentLookup | None = None
        self._resources: AramkitResources | None = None

    # ── 英雄元数据 ──────────────────────────────────────────────────────

    def _champions(self) -> dict[str, dict[str, Any]]:
        if self._champion_data is None:
            self._load_champions()
        assert self._champion_data is not None
        return self._champion_data

    def _load_champions(self) -> None:
        """加载英雄元数据并构建 key↔name 查找索引（一次性，供后续 O(1) 反查）。"""
        path = self._config.champion_dir
        if not path.exists():
            self._champion_data = {}
        else:
            files = [f for f in path.iterdir() if f.is_file()]
            if not files:
                self.logger.error(f"没有找到任何英雄数据文件在: {path}")
                self._champion_data = {}
            else:
                latest_file = max(files, key=lambda f: f.name)
                try:
                    with open(latest_file, "r", encoding="utf-8") as f:
                        self._champion_data = json.load(f)["data"]
                except Exception as e:
                    self.logger.error(f"读取英雄ID时发生错误: {str(e)}")
                    self._champion_data = {}
        self._champion_name_by_key = {}
        self._champion_key_by_name = {}
        for champ_info in self._champion_data.values():
            # key→name 用显示名 name；name→key 用内部标识 id（与原按 id 匹配的语义一致，
            # Data Dragon 部分英雄 id 与 name 不同，如 "Chogath" vs "Cho'Gath"），
            # 两者都映射到数字 key
            self._champion_name_by_key[str(champ_info["key"])] = str(champ_info["name"])
            self._champion_key_by_name[str(champ_info["id"]).lower()] = str(champ_info["key"])

    def champion_ids(self) -> list[str]:
        """全部英雄 ID（按整数升序）。"""
        return sorted((info["key"] for info in self._champions().values()), key=int)

    def champion_id_by_name(self, champion_name: str) -> str | None:
        """根据英雄名称获取英雄 ID（不区分大小写）。"""
        _ = self._champions()  # 确保索引已构建
        assert self._champion_key_by_name is not None
        champ_id = self._champion_key_by_name.get(champion_name.lower())
        if champ_id is None:
            self.logger.warning(f"未找到英雄名称 '{champion_name}' 对应的 ID")
        return champ_id

    def champion_name(self, champion_id: str) -> str | None:
        """根据英雄 ID（key）获取英雄名称。"""
        _ = self._champions()  # 确保索引已构建
        assert self._champion_name_by_key is not None
        name = self._champion_name_by_key.get(champion_id if isinstance(champion_id, str) else str(champion_id))
        if name is None:
            self.logger.warning(f"未找到英雄 ID '{champion_id}' 对应的名称")
        return name

    # ── 符文条目 ────────────────────────────────────────────────────────

    def _augment_data_path(self, champion_id: str, source: str) -> Path:
        """该英雄在指定数据源下的条目文件路径。"""
        if source == "aramkit":
            return self._config.aramkit_augment_dir / f"{champion_id}.json"
        return self._config.opgg_augment_dir / f"{champion_id}.json"

    def available_source(self, champion_id: str, preferred: str | None = None) -> str | None:
        """返回该英雄首个有符文数据的数据源（默认源优先，缺数据时回退另一源）。

        数据源切换后部分英雄仅存在于旧源（如 aramkit 爬取未覆盖的英雄），
        直接按默认源读取会抛 ``FileNotFoundError`` 中断推荐流程；本方法先检查
        文件存在性、静默跳过缺失的源，两个源都没有数据时返回 None。
        """
        preferred = preferred or self.default_source()
        other = "opgg" if preferred == "aramkit" else "aramkit"
        for source in (preferred, other):
            if not self._augment_data_path(champion_id, source).exists():
                continue
            try:
                if self.augment_entries(champion_id, source) is not None:
                    return source
            except (FileNotFoundError, json.JSONDecodeError):
                continue
        return None

    def augment_entries(self, champion_id: str, source: str | None = None) -> list[dict[str, Any]] | None:
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
        champion_data_path = self._augment_data_path(champion_id, source)
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
        if source == "aramkit":
            entries = convert_augment_records(raw_data.get("augments", {}).get("all", []))
        else:
            data = raw_data.get("data")
            if data is None:
                self.logger.warning(f"英雄符文数据文件缺少 'data' 字段: champion_id={champion_id}")
                entries = []
            else:
                entries = data
        self._entries_cache[cache_key] = entries
        return entries

    def augment_entries_all(self, source: str | None = None) -> dict[str, list[dict[str, Any]] | None]:
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

    def augment_info(self, augment_id: str) -> dict[str, Any] | None:
        """根据符文 ID 获取名称/等级信息：自动下载的 aramkit 资源优先，手动翻译表回退。

        翻译映射与数据源无关（opgg/aramkit 条目共用同一 ID 命名空间）；
        自动源跟随游戏版本更新，手动维护的 ``augment_trans.json`` 仅补齐
        aramkit 未收录的条目。
        """
        info = self._resources_impl().get_augment_info(augment_id)
        if info is None:
            info = self._lookup_impl().get_augment_info(augment_id)
        return info

    def augment_id(self, augment_name: str) -> str | None:
        """将符文名称反查为 ID：自动下载的 aramkit 资源优先，手动翻译表回退。

        两个来源均做 OCR 容错归一化（空格/连字符差异），匹配失败返回 None。
        """
        augment_id = self._resources_impl().get_augment_id(augment_name)
        if augment_id is None:
            augment_id = self._lookup_impl().get_augment_id(augment_name)
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
