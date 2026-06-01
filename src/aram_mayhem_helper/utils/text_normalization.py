"""OCR 文本规范化工具，修正常见字符误识别."""

DEFAULT_RULES: list[tuple[str, str]] = [
    ("—", "-"),  # em-dash (U+2014) — 常见 OCR 误识别为连字符
    ("–", "-"),  # en-dash (U+2013)
    ("－", "-"),  # 全角连字符 (U+FF0D)
]


def normalize_text(text: str, rules: list[tuple[str, str]] | None = None) -> str:
    """将文本中的 OCR 误识别字符替换为正确字符.

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
