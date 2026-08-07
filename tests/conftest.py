"""共享测试夹具：将 tests/fixtures/ 复制到临时数据目录并指向 config.data_path。"""

import json
import shutil
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_data_dir(tmp_path: Path) -> Path:
    """复制 fixtures 到 tmp_path/data，返回该目录。"""
    data_dir = tmp_path / "data"
    shutil.copytree(FIXTURES_DIR, data_dir)
    return data_dir


@pytest.fixture
def patch_config_data_path(monkeypatch: pytest.MonkeyPatch, fixture_data_dir: Path) -> Path:
    """将 config.data_path 指向 fixture 数据目录（数据类均在调用时读取该路径）。"""
    from aram_mayhem_helper.utils.config import config

    monkeypatch.setattr(config, "data_path", fixture_data_dir)
    return fixture_data_dir


@pytest.fixture
def fixture_trans_table() -> dict[str, dict]:
    """fixture 翻译表内容（augment_trans.json）。"""
    return json.loads((FIXTURES_DIR / "augment_trans.json").read_text(encoding="utf-8"))
