"""过滤/分组/打分共享流水线（Suggest 与 web 共用的核心管道）。"""

import logging
from collections.abc import Callable

from aram_mayhem_helper.algorithm.scoring import add_bayesian_sigmoid_score_attr, add_unit_scale_attr


def build_scored_groups(
    entries: list[dict],
    *,
    lookup: Callable[[str], dict | None],
    tau_factor: float,
    sigmoid_steepness: float,
    assign_rank: bool = True,
    champion_id: str | None = None,
    logger: logging.Logger | None = None,
) -> list[tuple[str, list[dict]]]:
    """过滤/分组/打分流水线。

    过滤规则（统一采用 web 的容错行为，与旧 Suggest 的差异见下）：
    - 缺 ``performance``/``popular`` → WARNING 并跳过
    - ``popular == 0`` → 跳过
    - 缺 ``id`` → WARNING 并跳过
    - ``lookup`` 未命中 → 跳过（旧 Suggest 会将其留在 ``champion_augment_data`` 中，
      统一后不再保留，属有意行为统一）

    每个 level 组执行 unit 缩放 + 贝叶斯-sigmoid 打分；
    打分失败（如单元素组方差为 0）记 WARNING 并保留组内项（无分数，旧 Suggest 会崩溃，
    统一为 web 的容错行为）。

    Args:
        entries: 原始符文条目（来自 GameData.augment_entries）
        lookup: 源感知的 augment_info 解析函数（``str(augment_id) → {"name", "level"}``）
        tau_factor: 贝叶斯收缩参数
        sigmoid_steepness: sigmoid 陡峭度
        assign_rank: 为 True 时按 weighted_sum 降序排序并赋 rank/group_size（Suggest 用）；
            web 保持文件顺序且不写 rank 字段
        champion_id: 日志上下文
        logger: 日志器

    Returns:
        [(level, items)]，按 level 首次出现顺序
    """
    log = logger or logging.getLogger(__name__)
    filtered: list[dict] = []
    for item in entries:
        perf = item.get("performance")
        pop = item.get("popular")
        if perf is None or pop is None:
            log.warning(f"英雄id:{champion_id}，符文数据项缺少 performance/popular 字段: {item}")
            continue
        if pop == 0:
            continue
        item_id = item.get("id")
        if item_id is None:
            log.warning(f"英雄id:{champion_id}，符文数据项缺少 'id' 字段: {item}")
            continue
        augment_info = lookup(str(item_id))
        if not augment_info:
            continue
        item["level"] = augment_info.get("level", "?")
        item["name"] = augment_info.get("name") or f"ID:{item_id}"
        filtered.append(item)

    by_level: dict[str, list[dict]] = {}
    for item in filtered:
        by_level.setdefault(item["level"], []).append(item)

    for level, items in by_level.items():
        try:
            # 统一数据源尺度：performance/popular 先 min-max 缩放到 [0,1]
            add_unit_scale_attr(items)
            add_bayesian_sigmoid_score_attr(
                items,
                perf_attr="performance_unit",
                pop_attr="popular_unit",
                new_attr="weighted_sum",
                tau_factor=tau_factor,
                sigmoid_steepness=sigmoid_steepness,
                perf_display_attr="performance_norm",
                pop_display_attr="popular_norm",
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
            # ZeroDivisionError：单元素组 unit 化后 popular 权重全 0，numpy 加权平均抛错
            log.warning(f"英雄 {champion_id} 等级 {level} 的符文数据归一化失败: {e}")
            continue
        if assign_rank:
            sorted_items = sorted(items, key=lambda x: x.get("weighted_sum", 0.0), reverse=True)
            by_level[level] = sorted_items
            for idx, item in enumerate(sorted_items):
                item["rank"] = idx + 1
                item["group_size"] = len(sorted_items)

    return [(level, items) for level, items in by_level.items()]
