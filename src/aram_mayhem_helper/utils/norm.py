import numpy as np


def get_normal_min_max(values: list) -> dict:
    """
    用IQR法筛选正常数据，返回正常数据的min/max（极端值不参与计算）
    :param values: 原始值列表
    :return: {"min": 正常数据最小值, "max": 正常数据最大值, "outliers": 极端值列表}
    """
    arr = np.array(values)
    q1 = np.percentile(arr, 25)  # 下四分位数
    q3 = np.percentile(arr, 75)  # 上四分位数
    iqr = q3 - q1

    # 正常数据范围
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr

    # 筛选正常数据和极端值
    normal_mask = (arr >= lower_bound) & (arr <= upper_bound)
    normal_values = arr[normal_mask]
    outlier_values = arr[~normal_mask].tolist()

    # 兜底：若所有数据都是极端值，用全部数据算min/max
    if len(normal_values) == 0:
        normal_values = arr

    return {"min": normal_values.min(), "max": normal_values.max(), "outliers": outlier_values}


def min_max_normalize(values: list, min_max_norm: bool) -> dict:
    """
    Min-Max标准化：将值缩放到0-1区间
    :param values: 原始值列表
    :return: 包含标准化函数+极值的字典（复用极值，避免重复计算）
    """

    if min_max_norm:
        norm_params = get_normal_min_max(values)
        min_val = norm_params["min"]
        max_val = norm_params["max"]
    else:
        min_val = min(values)
        max_val = max(values)

    # 处理极值相同的情况（避免除以0）
    if max_val == min_val:
        return {"normalize_func": lambda x: 0.0, "min": min_val, "max": max_val}

    # 定义标准化函数
    def normalize_func(x):
        return (x - min_val) / (max_val - min_val)

    return {"normalize_func": normalize_func, "min": min_val, "max": max_val}


def z_score_normalize(values: list) -> dict:
    """
    Z-score标准化：基于均值和标准差
    :param values: 原始值列表
    :return: 包含标准化函数+均值/标准差的字典
    """
    import numpy as np

    mean_val = np.mean(values)
    std_val = np.std(values)
    # 处理标准差为0的情况
    if std_val == 0:
        return {"normalize_func": lambda x: 0.0, "mean": mean_val, "std": std_val}

    # 定义标准化函数
    def normalize_func(x):
        return (x - mean_val) / std_val

    return {"normalize_func": normalize_func, "mean": mean_val, "std": std_val}


# ====================== 2. 给字典新增标准化属性 ======================
def add_normalized_attr(
    data_list: list,
    src_attr: str,  # 原始属性名（如"strength"）
    new_attr: str,  # 新增的标准化属性名（如"strength_norm"）
    normalize_type: str = "min-max",  # 标准化类型：min-max / z-score
    min_max_norm: bool = True,
) -> None:
    """
    给列表中每个字典新增标准化属性
    :param data_list: 目标列表（元素为字典）
    :param src_attr: 要标准化的原始属性名
    :param new_attr: 新增的标准化属性名
    :param normalize_type: 标准化类型
    :raises KeyError: 原始属性缺失时抛出
    :raises ValueError: 标准化类型错误时抛出
    """
    # 步骤1：提取所有原始属性值（校验字段完整性）
    src_values = []
    for idx, item in enumerate(data_list):
        if src_attr not in item:
            raise KeyError(f"第{idx}个元素缺失原始属性'{src_attr}': {item}")
        # 确保值是数值型（int/float）
        if not isinstance(item[src_attr], (int, float)):
            raise TypeError(f"第{idx}个元素的'{src_attr}'值不是数值型：{item[src_attr]}")
        src_values.append(item[src_attr])

    # 步骤2：选择标准化方式，生成标准化函数
    if normalize_type == "min-max":
        norm_info = min_max_normalize(src_values, min_max_norm)
    elif normalize_type == "z-score":
        norm_info = z_score_normalize(src_values)
    else:
        raise ValueError(f"不支持的标准化类型：{normalize_type}，可选：min-max / z-score")

    # 步骤3：给每个字典新增标准化属性
    for item in data_list:
        item[new_attr] = norm_info["normalize_func"](item[src_attr])
        # 可选：保留4位小数，避免精度冗余
        item[new_attr] = round(item[new_attr], 4)


def add_weighted_sum_attr(
    data_list: list,
    attr1: str,  # 第一个属性名
    attr2: str,  # 第二个属性名
    weight1: float,  # 第一个属性的权重
    weight2: float,  # 第二个属性的权重
    new_attr: str,  # 新增的加权求和属性名
) -> None:
    """
    给列表中每个字典新增加权求和属性：new_attr = attr1*weight1 + attr2*weight2
    :param data_list: 目标列表（元素为字典）
    :param attr1: 第一个属性名
    :param attr2: 第二个属性名
    :param weight1: 第一个属性的权重
    :param weight2: 第二个属性的权重
    :param new_attr: 新增的加权求和属性名
    :raises KeyError: 字典缺失属性时抛出
    :raises TypeError: 属性值非数值型时抛出
    """
    # 遍历每个字典，校验并计算
    for idx, item in enumerate(data_list):
        # 1. 校验两个属性是否存在
        if attr1 not in item:
            raise KeyError(f"第{idx}个元素缺失属性'{attr1}': {item}")
        if attr2 not in item:
            raise KeyError(f"第{idx}个元素缺失属性'{attr2}': {item}")

        # 2. 校验属性值是否为数值型（int/float）
        val1 = item[attr1]
        val2 = item[attr2]
        if not isinstance(val1, (int, float)):
            raise TypeError(f"第{idx}个元素的'{attr1}'值非数值：{val1}")
        if not isinstance(val2, (int, float)):
            raise TypeError(f"第{idx}个元素的'{attr2}'值非数值：{val2}")

        # 3. 计算加权求和
        weighted_sum = val1 * weight1 + val2 * weight2

        # 4. 新增属性到字典（保留2位小数，避免精度冗余）
        item[new_attr] = round(weighted_sum, 2)
