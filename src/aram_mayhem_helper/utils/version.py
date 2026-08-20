"""共享版本号解析与排序工具。"""

import re
from collections.abc import Iterable

VersionKey = tuple[tuple[int, ...], tuple[str, ...]]

_SUFFIX_PART_RE = re.compile(r"^[A-Za-z0-9._]+$")


def parse_version(value: str) -> VersionKey | None:
    """解析游戏版本号，返回数字发布段和可选后缀的排序键。

    支持 Data Dragon 版本（如 ``16.10.1``）以及 aramkit 版本
    （如 ``16.15-20260805-7e30d3443ba1``）。
    """
    if not isinstance(value, str) or not value:
        return None

    parts = value.split("-")
    release_parts = parts[0].split(".")
    if len(release_parts) < 2 or not all(part.isdecimal() for part in release_parts):
        return None

    suffix = tuple(parts[1:])
    if any(not part or _SUFFIX_PART_RE.fullmatch(part) is None for part in suffix):
        return None
    try:
        release = tuple(int(part) for part in release_parts)
    except ValueError:
        return None
    return release, suffix


def version_sort_key(version: str) -> VersionKey:
    """返回版本号排序键；版本格式无效时抛出 ``ValueError``。"""
    parsed = parse_version(version)
    if parsed is None:
        raise ValueError(f"无效版本号: {version!r}")
    return parsed


def latest_version(versions: Iterable[str]) -> str | None:
    """从版本号迭代器中返回最新版本；无有效版本时返回 ``None``。"""
    valid_versions = [(version, parsed) for version in versions if (parsed := parse_version(version)) is not None]
    return max(valid_versions, key=lambda item: item[1])[0] if valid_versions else None
