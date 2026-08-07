"""共享测试夹具：将 tests/fixtures/ 复制到临时数据目录并构造注入 fixture 的 GameData。"""

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from aram_mayhem_helper.utils.config import get_config
from aram_mayhem_helper.utils.data import GameData

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_data_dir(tmp_path: Path) -> Path:
    """复制 fixtures 到 tmp_path/data，返回该目录。"""
    data_dir = tmp_path / "data"
    shutil.copytree(FIXTURES_DIR, data_dir)
    return data_dir


@pytest.fixture
def app_config(fixture_data_dir: Path):
    """数据目录指向 fixture 的 AppConfig（其余配置沿用真实 config.toml）。"""
    return replace(get_config(), data_dir=fixture_data_dir)


@pytest.fixture
def game_data(app_config) -> GameData:
    """指向 fixture 数据目录的 GameData 仓储。"""
    return GameData(app_config)


@pytest.fixture
def fixture_trans_table() -> dict[str, dict]:
    """fixture 翻译表内容（augment_trans.json）。"""
    return json.loads((FIXTURES_DIR / "augment_trans.json").read_text(encoding="utf-8"))
