"""归一化与打分函数（自 utils/norm.py 迁移的活跃部分）。"""

import numpy as np


def add_unit_scale_attr(
    data_list: list,
    perf_attr: str = "performance",
    pop_attr: str = "popular",
    perf_unit_attr: str = "performance_unit",
    pop_unit_attr: str = "popular_unit",
) -> None:
    """
    将 performance/popular 按组内 min-max 缩放到 [0,1]，写入新字段（不覆盖原始值）。

    用于统一不同数据源的尺度：OP.GG 的 0~100 值与 aramkit 的 0~1 小数值
    在进入贝叶斯收缩前统一到 [0,1]，保证 tau（由 popular 中位数计算）的
    相对尺度一致，使双方打分结果尺度相同。

    Args:
        data_list: 目标列表（元素为字典），原地新增 unit 字段
        perf_attr: 表现原始属性名
        pop_attr: 流行度原始属性名
        perf_unit_attr: 表现缩放后属性名
        pop_unit_attr: 流行度缩放后属性名

    Raises:
        KeyError: 元素缺失原始属性
        TypeError: 属性值非数值型
    """
    if not data_list:
        return
    for src_attr, new_attr in ((perf_attr, perf_unit_attr), (pop_attr, pop_unit_attr)):
        values = []
        for idx, item in enumerate(data_list):
            if src_attr not in item:
                raise KeyError(f"第{idx}个元素缺失原始属性'{src_attr}': {item}")
            if not isinstance(item[src_attr], (int, float)):
                raise TypeError(f"第{idx}个元素的'{src_attr}'值不是数值型：{item[src_attr]}")
            values.append(item[src_attr])
        min_val = min(values)
        max_val = max(values)
        for item in data_list:
            if max_val == min_val:
                item[new_attr] = 0.0
            else:
                item[new_attr] = round((item[src_attr] - min_val) / (max_val - min_val), 4)


def add_bayesian_sigmoid_score_attr(
    data_list: list,
    perf_attr: str = "performance",
    pop_attr: str = "popular",
    new_attr: str = "weighted_sum",
    tau_factor: float = 0.5,
    sigmoid_steepness: float = 1.0,
    perf_display_attr: str = "",
    pop_display_attr: str = "",
) -> None:
    """Bayesian shrinkage + sigmoid squash into [0,1] in one pass.

    1. Auto-tau: τ = median(pop > 0) × tau_factor
    2. Bayesian shrinkage: adjusted = (pop/(pop+τ))×perf + (τ/(pop+τ))×level_mean
    3. Sigmoid: z = (adjusted - level_mean) / (level_std × steepness)
       final = 1 / (1 + exp(-z))  →  naturally in (0, 1)

    Parameters
    ----------
    data_list : list[dict]
        Mutated in-place — each dict receives ``new_attr``.
    perf_attr : str
        Key for the performance column (default ``"performance"``).
    pop_attr : str
        Key for the popularity column (default ``"popular"``).
    new_attr : str
        Key to write the final [0,1] score (default ``"weighted_sum"``
        for backward compatibility).
    tau_factor : float
        Multiplier for the auto-computed τ.  Smaller → more trust in
        raw performance of low-popularity augments.
    sigmoid_steepness : float
        Controls spread of the sigmoid.  >1 widens gaps; <1 compresses.
    perf_display_attr : str
        If set, store sigmoid(perf, group_mean, group_std) under this key.
    pop_display_attr : str
        If set, store percentile rank of popularity under this key.

    Raises
    ------
    ValueError
        If *data_list* is empty or the performance values have zero variance.
    """
    if not data_list:
        raise ValueError("data_list is empty, cannot compute Bayesian shrinkage")

    perf_values = []
    pop_values = []
    for idx, item in enumerate(data_list):
        if perf_attr not in item:
            raise KeyError(f"item {idx} missing key '{perf_attr}'")
        if pop_attr not in item:
            raise KeyError(f"item {idx} missing key '{pop_attr}'")
        perf_values.append(float(item[perf_attr]))
        pop_values.append(float(item[pop_attr]))

    perf_arr = np.array(perf_values)
    pop_arr = np.array(pop_values)

    level_mean: float = float(np.average(perf_arr, weights=pop_arr))
    # 加权标准差：高人气符文对分布宽度的贡献更大
    level_var: float = float(np.average((perf_arr - level_mean) ** 2, weights=pop_arr))
    level_std: float = float(np.sqrt(level_var))

    if level_std == 0:
        raise ValueError("performance std is 0, cannot apply sigmoid squash")

    # Auto-compute τ from the median of non-zero popularity values
    positive_pop = pop_arr[pop_arr > 0]
    if len(positive_pop) > 0:
        tau: float = float(np.median(positive_pop)) * tau_factor
    else:
        tau = 0.1 * tau_factor

    # Pre-compute popularity percentiles (1.0 = most popular)
    pop_percentiles: dict[int, float] = {}
    if pop_display_attr:
        n = len(pop_values)
        sorted_indices = sorted(range(n), key=lambda i: pop_values[i], reverse=True)
        for rank, idx in enumerate(sorted_indices):
            pop_percentiles[idx] = 1.0 - rank / max(n - 1, 1)

    for idx, item in enumerate(data_list):
        perf = float(item[perf_attr])
        pop = float(item[pop_attr])

        # Bayesian shrinkage toward level mean
        denom = pop + tau
        weight = pop / denom if denom > 0 else 0.0
        adjusted = weight * perf + (1.0 - weight) * level_mean

        # Sigmoid squash → [0, 1]
        divisor = level_std * sigmoid_steepness
        z = (adjusted - level_mean) / divisor if divisor > 0 else 0.0
        final_score = 1.0 / (1.0 + np.exp(-z))

        item[new_attr] = round(float(final_score), 4)

        # Per-dimension display values
        if perf_display_attr:
            perf_z = (perf - level_mean) / divisor if divisor > 0 else 0.0
            item[perf_display_attr] = round(float(1.0 / (1.0 + np.exp(-perf_z))), 4)
        if pop_display_attr:
            item[pop_display_attr] = round(pop_percentiles[idx], 4)
