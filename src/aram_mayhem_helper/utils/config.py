"""配置加载：TOML → 冻结数据类，支持显式路径与环境变量注入。"""

import os
import re
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
class OcrConfig:
    """OCR 工具配置（GUI / recommend 命令）。"""

    debug_save_captures: bool = False  # 调试模式：每次识别把每个区域截图保存到日志目录


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
    ocr: OcrConfig
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

    @property
    def ocr_failure_dir(self) -> Path:
        """OCR 识别失败（符文名称未匹配）时保存区域截图的目录。"""
        return self.log_dir / "ocr_failures"

    @property
    def ocr_debug_dir(self) -> Path:
        """OCR 调试模式（每次识别保存全部区域截图）的目录。"""
        return self.log_dir / "ocr_debug"


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
    ocr_raw = _as_section(raw, "ocr")

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
        ocr=OcrConfig(
            debug_save_captures=bool(_get(ocr_raw, "debug_save_captures", default=False)),
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


# ── 数据源写回（GUI 切换数据源持久化）──────────────────────────────────────

_SECTION_HEADER_RE = re.compile(r"^\[(?P<name>[^\]]+)\]")
_SOURCE_VALUE_RE = re.compile(
    r'^(?P<indent>[ \t]*)source[ \t]*=[ \t]*(?P<quote>["\'])(?P<old>[^"\']*)(?P=quote)(?P<tail>.*)$'
)


def _rewrite_data_source_text(content: str, source: str) -> str:
    """纯函数：替换 config.toml 文本中 ``[data_source]`` 段内 source 的值。

    逐行扫描并跟踪当前段落，只改 ``data_source`` 段内的 ``source = "..."`` 行；
    保留注释、缩进、行尾内容与换行风格（含 CRLF）。单/双引号值均可识别，
    替换时统一规范化为双引号。段落或键缺失时抛 ``ValueError``（不写盘）。

    Args:
        content: config.toml 原始文本
        source: 新数据源（"opgg"/"aramkit"）
    """
    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.split(newline)
    in_data_source = False
    section_seen = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            match = _SECTION_HEADER_RE.match(stripped)
            # TOML 允许表头内包围空白与引号键（[ data_source ] / ["data_source"]）
            in_data_source = bool(match and match.group("name").strip().strip('"') == "data_source")
            section_seen = section_seen or in_data_source
            continue
        if in_data_source:
            match = _SOURCE_VALUE_RE.match(line)
            if match:
                if match.group("old") == source:
                    return content  # 值未变，原样返回
                lines[i] = f'{match.group("indent")}source = "{source}"{match.group("tail")}'
                return newline.join(lines)
    if not section_seen:
        raise ValueError("config.toml 中未找到 [data_source] 段落")
    raise ValueError("config.toml 的 [data_source] 段中未找到 source 配置行")


def set_data_source(source: str) -> AppConfig:
    """持久化写入数据源到 config.toml，重建配置单例并返回新配置。

    校验通过后以「同目录临时文件 + os.replace」原子写回（保留注释与其他内容），
    随后按原 config_path/data_dir 重建 ``_config_singleton``，使后续 ``get_config()``
    读到新值。

    Args:
        source: 数据源（"opgg"/"aramkit"）

    Raises:
        ValueError: source 非法，或 config.toml 缺少 [data_source].source
        OSError: 文件读取/写入失败
    """
    global _config_singleton
    if source not in VALID_SOURCES:
        raise ValueError(f"非法数据源 {source!r}，可选: {', '.join(VALID_SOURCES)}")

    current = get_config()
    if current.data_source.source == source:
        return current

    # newline="" 显式往返：保留原始换行风格（含 CRLF），不依赖平台换行翻译
    with current.config_path.open(encoding="utf-8", newline="") as f:
        content = f.read()
    new_content = _rewrite_data_source_text(content, source)

    tmp_path = current.config_path.with_name(current.config_path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="") as f:
            f.write(new_content)
        os.replace(tmp_path, current.config_path)  # 同目录 → 同卷，Windows 原子替换
    except OSError:
        tmp_path.unlink(missing_ok=True)  # 清理半成品
        raise

    # 重建单例时沿用旧 data_dir，保留 env/参数注入的 data_dir 语义
    _config_singleton = load_config(config_path=current.config_path, data_dir=current.data_dir)
    return _config_singleton
