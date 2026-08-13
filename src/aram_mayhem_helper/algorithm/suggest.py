"""符文推荐引擎：分组打分 + 阈值建议（"快选"/"考虑"/"垃圾"）。"""

import logging
from collections.abc import Callable
from typing import Any

from aram_mayhem_helper.algorithm.pipeline import build_scored_groups
from aram_mayhem_helper.utils.config import SuggestConfig
from aram_mayhem_helper.utils.data import GameData


class Suggest:
    """对单个英雄的符文数据进行打分与推荐。

    Args:
        champion_id: 英雄 ID
        data: GameData 仓储（注入，便于测试与多实例）
        source: 数据源（"opgg"/"aramkit"），None 取配置默认
        thresholds: 推荐阈值（实例数据，替代旧实现的类属性在导入时读配置）
    """

    def __init__(
        self,
        champion_id: str,
        data: GameData,
        *,
        source: str | None = None,
        thresholds: SuggestConfig,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.champion_id = champion_id
        self.data = data
        self.source = source or data.default_source()
        self.thresholds = thresholds

        entries = data.augment_entries(champion_id, self.source)
        if entries is None:
            entries = []

        self.champion_augment_data: list[dict[str, Any]] = []
        self.augment_group: dict[str, dict[str, Any]] = {}
        groups = build_scored_groups(
            entries,
            lookup=lambda augment_id: data.augment_info(augment_id, self.source),
            tau_factor=thresholds.shrinkage_tau_factor,
            sigmoid_steepness=thresholds.sigmoid_steepness,
            assign_rank=True,
            champion_id=champion_id,
            logger=self.logger,
        )
        for level, items in groups:
            self.augment_group[level] = {"augments": items, "number": len(items)}
            self.champion_augment_data.extend(items)

    def get_augment_info_by_id(self, augment_id: str) -> dict[str, Any] | None:
        """
        使用符文id查询对应符文信息

        Args:
            augment_id (str): 符文id

        Returns:
            dict | None: 符文信息，未找到时返回 None
        """
        if not augment_id:
            return None
        for item in self.champion_augment_data:
            item_id = item.get("id")
            if item_id is not None and str(item_id) == augment_id:
                return item
        return None

    def suggest(
        self,
        augments: list[str],
        *,
        on_unrecognized: Callable[[int, str], None] | None = None,
    ) -> list[str]:
        """
        根据输入符文信息，给出操作推荐

        Args:
            augments (list[str]): 输入符文信息
            on_unrecognized: 可选回调；符文名称无法匹配时以 (区域索引, OCR文本)
                调用，便于调用方保存该区域识别画面用于后期排查

        Returns:
            list: 操作推荐
        """
        augment_info: list[dict[str, Any]] = []
        for index, augment in enumerate(augments):
            augment_id = self.data.augment_id(augment, self.source)
            if not augment_id:
                self.logger.warning(f"无法识别符文名称 '{augment}'，翻译文件中未找到匹配")
                if on_unrecognized is not None:
                    on_unrecognized(index, augment)
                continue
            info = self.get_augment_info_by_id(augment_id)
            if not info:
                self.logger.warning(f"符文 ID {augment_id} (OCR名称: '{augment}') 在当前英雄数据中未找到")
                continue
            augment_info.append(info)
        if not augment_info:
            self.logger.warning("没有有效的符文信息可供建议")
            return []
        result = self.get_suggest_info(augment_info)
        return result

    def get_suggest_info(self, augments: list[dict[str, Any]]) -> list[str]:
        """
        根据输入符文信息，给出操作推荐

        Args:
            augments (list[dict[str, Any]]): 输入符文信息

        Returns:
            list: 操作推荐
        """
        if not augments:
            return []
        first = augments[0]
        if first is None:
            self.logger.warning("符文信息列表首元素为 None，无法生成建议")
            return []
        augments_num = first.get("group_size")
        if augments_num is None:
            self.logger.warning("符文数据缺少 'group_size' 字段，无法生成建议")
            return []
        t = self.thresholds
        immediate_select_rank_threshold = augments_num * t.immediate_select_percentage_threshold
        consider_select_rank_threshold = augments_num * t.consider_select_percentage_threshold
        max_weighted_sum = max(item.get("weighted_sum", 0) for item in augments if item is not None)
        result: list[str] = []
        for augment in augments:
            if augment is None:
                continue
            name = augment.get("name", "未知")
            rank = augment.get("rank", augments_num)
            ws = augment.get("weighted_sum", 0)
            perf_norm = augment.get("performance_norm", "N/A")
            pop_norm = augment.get("popular_norm", "N/A")
            message = None
            if rank <= immediate_select_rank_threshold or ws >= t.immediate_select_score_threshold:
                message = f"快选符文：{name}，别的不用看了"
            elif rank <= consider_select_rank_threshold or ws >= t.consider_select_score_threshold:
                if max_weighted_sum == ws:
                    message = f"考虑符文：{name}，暂时先别换"
                else:
                    message = f"考虑符文：{name}，可以随掉"
            else:
                message = f"垃圾符文: {name}，别选，太垃圾了"
            message += f"，{rank}/{augments_num}，表现: {perf_norm}，流行度: {pop_norm}"
            result.append(message)

        return result
