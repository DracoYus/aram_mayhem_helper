"""Build script: copy required data files into deploy/data/.

Run from the project root:
    python deploy/build.py
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DATA = Path(__file__).resolve().parent / "data"

SRC_CHAMPIONS = ROOT / "data" / "ddragon" / "champions"
SRC_AUGMENTS = ROOT / "data" / "opgg" / "aram_augments"
SRC_TRANS = ROOT / "data" / "augment_trans.json"
SRC_CHAMPION_I18N = ROOT / "data" / "champions-names-i18n.json"
SRC_AUGMENT_DESC = ROOT / "data" / "aram-mayhem-augments.zh_cn.json"


def main() -> None:
    # Clean existing
    if DEPLOY_DATA.exists():
        shutil.rmtree(DEPLOY_DATA)

    # Champion data — pick the latest version
    champ_files = sorted(SRC_CHAMPIONS.glob("*.json"), key=lambda f: f.name, reverse=True)
    if not champ_files:
        print("ERROR: 未找到英雄数据文件")
        return
    latest = champ_files[0]
    dst_champ_dir = DEPLOY_DATA / "ddragon" / "champions"
    dst_champ_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(latest, dst_champ_dir / latest.name)
    print(f"已复制英雄数据: {latest.name}")

    # Augment data — all champion files
    dst_aug_dir = DEPLOY_DATA / "opgg" / "aram_augments"
    dst_aug_dir.mkdir(parents=True, exist_ok=True)
    aug_count = 0
    for f in SRC_AUGMENTS.glob("*.json"):
        shutil.copy2(f, dst_aug_dir / f.name)
        aug_count += 1
    print(f"已复制符文数据: {aug_count} 个文件")

    # Translation files
    if SRC_TRANS.exists():
        shutil.copy2(SRC_TRANS, DEPLOY_DATA / "augment_trans.json")
        print("已复制符文翻译文件")
    if SRC_CHAMPION_I18N.exists():
        shutil.copy2(SRC_CHAMPION_I18N, DEPLOY_DATA / "champions-names-i18n.json")
        print("已复制英雄 i18n 文件")
    if SRC_AUGMENT_DESC.exists():
        shutil.copy2(SRC_AUGMENT_DESC, DEPLOY_DATA / "aram-mayhem-augments.zh_cn.json")
        print("已复制符文描述文件")

    print("\n构建完成！部署步骤：")
    print("  1. cd deploy")
    print("  2. pip install -r requirements.txt")
    print("  3. python app.py")
    print("  4. 浏览器打开 http://127.0.0.1:5000")
    print("\nDocker 部署：")
    print("  docker build -t aram-web deploy/")
    print("  docker run -p 5000:5000 aram-web")


if __name__ == "__main__":
    main()
