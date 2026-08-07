"""配置加载：TOML → 冻结数据类，支持显式路径与环境变量注入。"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ENV_CONFIG_DIR = "ARAM_MAYHEM_CONFIG_DIR"
_ENV_DATA_DIR = "ARAM_MAYHEM_DATA_DIR"
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_PATH = _DEFAULT_REPO_ROOT / "config" / "config.toml"

VALID_SOURCES = ("opgg", "aramkit")


# ── 配置数据类 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OpggAugmentConfig:
    base_url: str
    save_directory: str


@dataclass(frozen=True)
class DdragonChampionConfig:
    base_url: str
    save_directory: str


@dataclass(frozen=True)
class AramkitAugmentConfig:
    data_base_url: str
    dataset: str
    save_directory: str


@dataclass(frozen=True)
class AramkitResourcesConfig:
    resources_base_url: str
    language: str
    save_directory: str


@dataclass(frozen=True)
class AramkitConfig:
    homepage_url: str
    augment: AramkitAugmentConfig
    resources: AramkitResourcesConfig


@dataclass(frozen=True)
class CrawlerConfig:
    timeout: int
    delay_second: float
    user_agent: str
    opgg_augment: OpggAugmentConfig
    ddragon_champion: DdragonChampionConfig
    aramkit: AramkitConfig


@dataclass(frozen=True)
class DataSourceConfig:
    source: str  # "opgg" | "aramkit"，非法值在 load_config 时回退 "opgg"


@dataclass(frozen=True)
class SuggestConfig:
    shrinkage_tau_factor: float = 0.5
    sigmoid_steepness: float = 1.0
    immediate_select_score_threshold: float = 0.70
    consider_select_score_threshold: float = 0.50
    immediate_select_percentage_threshold: float = 0.10
    consider_select_percentage_threshold: float = 0.30


@dataclass(frozen=True)
class AppConfig:
    """全量应用配置，含已解析的数据路径。"""

    crawler: CrawlerConfig
    data_source: DataSourceConfig
    suggest: SuggestConfig
    project_root: Path
    data_dir: Path
    config_path: Path
    raw: dict[str, Any]  # 原始 TOML，供旧 Config 兼容层嵌套查询

    @property
    def champion_dir(self) -> Path:
        return self.data_dir / self.crawler.ddragon_champion.save_directory

    @property
    def opgg_augment_dir(self) -> Path:
        return self.data_dir / self.crawler.opgg_augment.save_directory

    @property
    def aramkit_augment_dir(self) -> Path:
        return self.data_dir / self.crawler.aramkit.augment.save_directory / self.crawler.aramkit.augment.dataset

    @property
    def aramkit_resources_dir(self) -> Path:
        return self.data_dir / self.crawler.aramkit.resources.save_directory

    @property
    def trans_file(self) -> Path:
        return self.data_dir / "augment_trans.json"

    @property
    def i18n_file(self) -> Path:
        return self.data_dir / "champions-names-i18n.json"

    @property
    def augment_desc_file(self) -> Path:
        return self.data_dir / "aram-mayhem-augments.zh_cn.json"

    @property
    def log_dir(self) -> Path:
        return self.project_root / "logs"


# ── 加载器 ────────────────────────────────────────────────────────────────


def _get(section: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """嵌套查询原始 TOML 段落。"""
    value: Any = section
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
        if value is None:
            return default
    return value


def load_config(*, config_path: Path | None = None, data_dir: Path | None = None) -> AppConfig:
    """从 TOML 加载配置为冻结数据类。

    解析顺序：
    - ``config_path`` ← env ``ARAM_MAYHEM_CONFIG_DIR``/config.toml ← 仓库默认路径
    - ``data_dir`` ← env ``ARAM_MAYHEM_DATA_DIR`` ← 参数 ← ``config_path.parent.parent / "data"``

    Args:
        config_path: 显式指定 config.toml 路径
        data_dir: 显式指定数据目录

    Raises:
        FileNotFoundError: config.toml 不存在（与旧 Config 行为一致）
    """
    if config_path is None:
        env_config_dir = os.environ.get(_ENV_CONFIG_DIR)
        config_path = Path(env_config_dir) / "config.toml" if env_config_dir else _DEFAULT_CONFIG_PATH
    config_path = config_path.resolve()

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    if data_dir is None:
        env_data_dir = os.environ.get(_ENV_DATA_DIR)
        data_dir = Path(env_data_dir) if env_data_dir else config_path.parent.parent / "data"
    data_dir = data_dir.resolve()

    with config_path.open("rb") as f:
        raw = tomllib.load(f)

    crawler_raw = _as_section(raw, "crawler")
    suggest_raw = _as_section(raw, "suggest")

    def suggest_float(old_key: str, new_key: str, default: float) -> float:
        # 正确拼写优先，旧拼写（precentage）回退兼容
        return float(_get(suggest_raw, new_key, default=_get(suggest_raw, old_key, default=default)))

    source_raw = str(_get(raw, "data_source", "source", default="opgg"))
    source = source_raw if source_raw in VALID_SOURCES else "opgg"

    app = AppConfig(
        crawler=CrawlerConfig(
            timeout=int(_get(crawler_raw, "timeout", default=30)),
            delay_second=float(_get(crawler_raw, "delay_second", default=2)),
            user_agent=str(_get(crawler_raw, "user_agent", default="")),
            opgg_augment=OpggAugmentConfig(
                base_url=str(_get(crawler_raw, "opgg", "aram_augment", "base_url", default="")),
                save_directory=str(
                    _get(crawler_raw, "opgg", "aram_augment", "save_directory", default="opgg/aram_augments/")
                ),
            ),
            ddragon_champion=DdragonChampionConfig(
                base_url=str(_get(crawler_raw, "ddragon", "champion", "base_url", default="")),
                save_directory=str(
                    _get(crawler_raw, "ddragon", "champion", "save_directory", default="ddragon/champions/")
                ),
            ),
            aramkit=AramkitConfig(
                homepage_url=str(_get(crawler_raw, "aramkit", "homepage_url", default="")),
                augment=AramkitAugmentConfig(
                    data_base_url=str(_get(crawler_raw, "aramkit", "aram_augment", "data_base_url", default="")),
                    dataset=str(_get(crawler_raw, "aramkit", "aram_augment", "dataset", default="all")),
                    save_directory=str(
                        _get(crawler_raw, "aramkit", "aram_augment", "save_directory", default="aramkit/aram_augments/")
                    ),
                ),
                resources=AramkitResourcesConfig(
                    resources_base_url=str(_get(crawler_raw, "aramkit", "resources", "resources_base_url", default="")),
                    language=str(_get(crawler_raw, "aramkit", "resources", "language", default="zh-CN")),
                    save_directory=str(
                        _get(crawler_raw, "aramkit", "resources", "save_directory", default="aramkit/resources/")
                    ),
                ),
            ),
        ),
        data_source=DataSourceConfig(source=source),
        suggest=SuggestConfig(
            shrinkage_tau_factor=suggest_float("shrinkage_tau_factor", "shrinkage_tau_factor", 0.5),
            sigmoid_steepness=suggest_float("sigmoid_steepness", "sigmoid_steepness", 1.0),
            immediate_select_score_threshold=suggest_float(
                "immediate_select_score_threshold", "immediate_select_score_threshold", 0.70
            ),
            consider_select_score_threshold=suggest_float(
                "consider_select_score_threshold", "consider_select_score_threshold", 0.50
            ),
            immediate_select_percentage_threshold=suggest_float(
                "immediate_select_precentage_threshold", "immediate_select_percentage_threshold", 0.10
            ),
            consider_select_percentage_threshold=suggest_float(
                "consider_select_precentage_threshold", "consider_select_percentage_threshold", 0.30
            ),
        ),
        project_root=_DEFAULT_REPO_ROOT,
        data_dir=data_dir,
        config_path=config_path,
        raw=raw,
    )
    return app


def _as_section(raw: dict[str, Any], section: str) -> dict[str, Any]:
    value = raw.get(section)
    return value if isinstance(value, dict) else {}


_config_singleton: AppConfig | None = None


def get_config() -> AppConfig:
    """懒加载单例配置（替代旧导入期 ``config = Config()`` 的副作用）。"""
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = load_config()
    return _config_singleton


# ── 旧调用方兼容层（Phase 3/4 迁移完成后移除）─────────────────────────────


class Config:
    """兼容旧调用方的委托类：保持嵌套 get() 与可变 data_path 行为。"""

    def __init__(self) -> None:
        app = get_config()
        self.base_dir: Path = app.project_root
        self.config_path: Path = app.config_path
        self.data_path: Path = app.data_dir
        self._app_config: AppConfig = app

    def get(self, *keys: str, default: Any = None) -> Any:
        """嵌套读取原始 TOML（``config.get("suggest", "immediate_select_score_threshold")``）。"""
        return _get(self._app_config.raw, *keys, default=default)

    @property
    def data(self) -> dict[str, Any]:
        return self._app_config.raw


config = Config()
