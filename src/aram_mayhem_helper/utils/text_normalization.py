"""OCR 文本规范化工具，修正常见字符误识别."""

import unicodedata

# 仍保留精确字面对照规则，用于修正 OCR 的语义级误识别
DEFAULT_RULES: list[tuple[str, str]] = [
    ("进", "迸"),
    ("鸣", "呜"),
    ("堂", "掌"),
]


def normalize_text(text: str, rules: list[tuple[str, str]] | None = None) -> str:
    """将文本中的 OCR 语义误识别字符替换为正确字符.

    注意：此函数不处理连字符和空白，这些由 normalize_for_lookup() 统一处理。

    Args:
        text: 待规范化的原始文本
        rules: 替换规则列表 [(from, to), ...], 默认使用 DEFAULT_RULES

    Returns:
        规范化后的文本
    """
    if not text:
        return text
    if rules is None:
        rules = DEFAULT_RULES
    for from_char, to_char in rules:
        text = text.replace(from_char, to_char)
    return text


# CJK 字符中酷似横线的字符，OCR 常将其误读为连字符（Pd）
_OCR_DASH_MISREADS: set[str] = {"一"}  # 一 (U+4E00) — OCR 经常把细 ASCII "-" 错读成这个字


def normalize_for_lookup(text: str) -> str:
    """归一化文本用于模糊匹配查找，消除 OCR 产出的不可控格式差异.

    规则（按顺序）：
    1. 所有 Unicode 连字符（Pd 类别）统一为 ASCII ``-``
    2. 常见 OCR 横线误读字符（如 ``一``）也统一为 ASCII ``-``
    3. 所有 Unicode 空白字符（Z 类别）直接丢弃
    4. 应用 normalize_text() 修正语义错字

    Pd (Dash Punctuation) 示例：``-`` ``–`` ``—`` ``―`` ``‑`` ``﹘`` ``－`` ...
    Z (Separator) 示例：       `` `` ``　`` ``\t`` `` `` ...

    Args:
        text: 待归一化的原始文本

    Returns:
        归一化后的文本
    """
    if not text:
        return text

    result = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Pd" or ch in _OCR_DASH_MISREADS:
            result.append("-")
        elif not (cat.startswith("Z") or cat == "Cc"):
            result.append(ch)
        # Z 类（空白分隔符）和 Cc 类（控制字符）直接丢弃

    return normalize_text("".join(result))
