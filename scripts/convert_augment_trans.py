"""将 aram-mayhem-augments.zh_cn.json 转换为 augment_trans.json 格式。

数据来源: data/aram-mayhem-augments.zh_cn.json
输出目标: data/augment_trans.json (完全覆盖)

映射关系:
    displayName -> name
    rarity      -> level (转为字符串)
"""

import json
from pathlib import Path


def convert(source_path: Path, target_path: Path) -> None:
    """读取源元数据，转换为 augment_trans.json 格式并写入目标文件。"""
    with open(source_path, encoding="utf-8") as f:
        raw = json.load(f)

    result: dict[str, dict[str, str]] = {}
    for aug_id, aug_data in raw.items():
        result[aug_id] = {
            "name": aug_data["displayName"],
            "level": str(aug_data["rarity"]),
        }

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    print(f"转换完成: {len(result)} 条符文数据 -> {target_path}")


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    source = project_root / "data" / "aram-mayhem-augments.zh_cn.json"
    target = project_root / "data" / "augment_trans.json"

    if not source.exists():
        raise FileNotFoundError(f"源文件不存在: {source}")

    convert(source, target)


if __name__ == "__main__":
    main()
