"""共享推荐流程：识别当前英雄 → 解析数据源 → OCR → 生成建议。

CLI（``cli.recommend``）与 GUI（``gui._recognize_worker``）共用此流程，
消除两份拷贝间的行为漂移（历史上 GUI 的数据源回退日志与 CLI 不一致）。
"""

import logging
from dataclasses import dataclass
from typing import Any

from aram_mayhem_helper.algorithm.suggest import Suggest
from aram_mayhem_helper.league_client_api.live_data import get_current_champion_name
from aram_mayhem_helper.ocr.ocr_tool import OCRTool, save_unrecognized_capture
from aram_mayhem_helper.utils.config import get_config
from aram_mayhem_helper.utils.data import GameData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecommendOutcome:
    """一次推荐流程的结果（供调用方决定如何展示）。"""

    lines: list[str]  # 建议行（"快选符文：..." 等），空列表表示无建议
    champion_name: str | None = None  # 识别到的英雄名（未识别到为 None）
    source: str | None = None  # 实际使用的数据源


def run_recommend(
    game_data: GameData,
    ocr_tool: OCRTool,
    *,
    preferred_source: str | None = None,
    on_unrecognized: Any = save_unrecognized_capture,  # noqa: B008 - 回调默认值，非可变对象
) -> RecommendOutcome:
    """执行一次完整推荐流程，返回结构化结果；所有失败路径仅记日志并返回。

    流程：查询当前英雄 → 名称→ID → 数据源解析（缺数据回退另一源）→
    构造 Suggest（打分）→ OCR 读取符文 → 匹配并生成建议。

    Args:
        game_data: 数据仓储
        ocr_tool: OCR 工具（调用方注入，便于测试）
        preferred_source: GUI 显式传入所选数据源；None 时取配置默认
        on_unrecognized: OCR 名称未匹配时的回调（(区域索引, OCR文本)）
    """
    try:
        champion_name = get_current_champion_name()
        if not champion_name:
            logger.error("无法获取当前英雄名称，请确保游戏正在运行")
            return RecommendOutcome(lines=[])

        champion_id = game_data.champion_id_by_name(champion_name)
        if not champion_id:
            logger.error(f"无法找到英雄 '{champion_name}' 对应的ID")
            return RecommendOutcome(lines=[])

        resolved = game_data.available_source(champion_id, preferred=preferred_source)
        if resolved is None:
            logger.error(f"英雄ID {champion_id} ({champion_name}) 在两个数据源中都没有符文数据")
            return RecommendOutcome(lines=[])

        if resolved != (preferred_source or game_data.default_source()):
            logger.warning(
                f"数据源 {preferred_source or game_data.default_source()} 无该英雄的符文数据，已回退使用 {resolved}"
            )

        suggest = Suggest(champion_id, game_data, source=resolved, thresholds=get_config().suggest)
        logger.info(f"当前英雄：{champion_name}（数据源: {resolved}）")
    except Exception as e:
        logger.error(f"识别英雄出错：{str(e)}")
        return RecommendOutcome(lines=[])

    augments: list[str] | None = None
    try:
        augments = ocr_tool.get_augments()
        augments_info = suggest.suggest(augments, on_unrecognized=on_unrecognized)
        if augments_info:
            for augment_info in augments_info:
                logger.info(str(augment_info))
        else:
            logger.warning("未能生成任何符文建议（OCR 名称未匹配到当前英雄的符文数据）")
        return RecommendOutcome(lines=augments_info, champion_name=champion_name, source=resolved)
    except Exception as e:
        logger.error(f"「识别符文」操作出错：{str(e)}")
        if augments is not None:
            logger.info(str(augments))
        return RecommendOutcome(lines=[], champion_name=champion_name, source=resolved)
