"""utils.config 配置加载行为测试（TOML → 冻结数据类、拼写回退、env 注入）。"""

from pathlib import Path

import pytest

from aram_mayhem_helper.utils.config import (
    DataSourceConfig,
    get_config,
    load_config,
)

MINIMAL_TOML = """
[crawler]
timeout = 30
delay_second = 2
user_agent = "Mozilla/5.0 Test"

[crawler.opgg.aram_augment]
base_url = "https://op.example/api/{0}"
save_directory = "opgg/aram_augments/"

[crawler.ddragon.champion]
base_url = "https://dd.example/cdn/{0}/champion.json"
save_directory = "ddragon/champions/"

[crawler.aramkit]
homepage_url = "https://aramkit.example/"

[crawler.aramkit.aram_augment]
data_base_url = "https://data.example/data/"
dataset = "all"
save_directory = "aramkit/aram_augments/"

[crawler.aramkit.resources]
resources_base_url = "https://data.example/resources/"
language = "zh-CN"
save_directory = "aramkit/resources/"

[data_source]
source = "aramkit"

[suggest]
shrinkage_tau_factor = 0.5
sigmoid_steepness = 1.0
immediate_select_score_threshold = 0.70
consider_select_score_threshold = 0.50
immediate_select_precentage_threshold = 0.10
consider_select_precentage_threshold = 0.30
"""


def _write_config(tmp_path: Path, content: str = MINIMAL_TOML) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    config_path.write_text(content, encoding="utf-8")
    return config_path


class TestLoadConfig:
    def test_parses_full_toml(self, tmp_path) -> None:
        cfg = load_config(config_path=_write_config(tmp_path))
        assert cfg.crawler.timeout == 30
        assert cfg.crawler.delay_second == 2
        assert cfg.crawler.user_agent == "Mozilla/5.0 Test"
        assert cfg.crawler.opgg_augment.base_url == "https://op.example/api/{0}"
        assert cfg.crawler.ddragon_champion.save_directory == "ddragon/champions/"
        assert cfg.crawler.aramkit.homepage_url == "https://aramkit.example/"
        assert cfg.crawler.aramkit.augment.dataset == "all"
        assert cfg.crawler.aramkit.resources.language == "zh-CN"
        assert cfg.data_source.source == "aramkit"
        assert cfg.suggest.shrinkage_tau_factor == 0.5
        assert cfg.suggest.immediate_select_score_threshold == 0.70
        assert cfg.suggest.consider_select_score_threshold == 0.50

    def test_data_dir_defaults_next_to_config(self, tmp_path) -> None:
        cfg = load_config(config_path=_write_config(tmp_path))
        assert cfg.data_dir == (tmp_path / "data").resolve()
        assert cfg.project_root == Path(__file__).resolve().parents[1]

    def test_typo_spelling_accepted_into_new_fields(self, tmp_path) -> None:
        cfg = load_config(config_path=_write_config(tmp_path))
        # 旧拼写 precentage 键 → 新字段 percentage
        assert cfg.suggest.immediate_select_percentage_threshold == 0.10
        assert cfg.suggest.consider_select_percentage_threshold == 0.30

    def test_correct_spelling_wins_over_typo(self, tmp_path) -> None:
        content = MINIMAL_TOML.replace(
            "immediate_select_precentage_threshold = 0.10",
            "immediate_select_precentage_threshold = 0.10\nimmediate_select_percentage_threshold = 0.42",
        )
        cfg = load_config(config_path=_write_config(tmp_path, content))
        assert cfg.suggest.immediate_select_percentage_threshold == 0.42

    def test_invalid_source_falls_back_to_opgg(self, tmp_path) -> None:
        content = MINIMAL_TOML.replace('source = "aramkit"', 'source = "invalid"')
        cfg = load_config(config_path=_write_config(tmp_path, content))
        assert cfg.data_source.source == "opgg"

    def test_missing_config_raises_file_not_found(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(config_path=tmp_path / "nope" / "config.toml")

    def test_env_config_dir_override(self, tmp_path, monkeypatch) -> None:
        config_path = _write_config(tmp_path)
        monkeypatch.setenv("ARAM_MAYHEM_CONFIG_DIR", str(config_path.parent))
        cfg = load_config()
        assert cfg.config_path == config_path.resolve()
        # data_dir 跟随 config 所在仓库布局
        assert cfg.data_dir == (tmp_path / "data").resolve()

    def test_env_data_dir_override(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("ARAM_MAYHEM_DATA_DIR", str(tmp_path / "mydata"))
        cfg = load_config(config_path=_write_config(tmp_path))
        assert cfg.data_dir == (tmp_path / "mydata").resolve()

    def test_explicit_data_dir_beats_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("ARAM_MAYHEM_DATA_DIR", str(tmp_path / "envdata"))
        cfg = load_config(config_path=_write_config(tmp_path), data_dir=tmp_path / "argdata")
        assert cfg.data_dir == (tmp_path / "argdata").resolve()

    def test_resolved_path_properties(self, tmp_path) -> None:
        cfg = load_config(config_path=_write_config(tmp_path))
        assert cfg.opgg_augment_dir == cfg.data_dir / "opgg" / "aram_augments"
        assert cfg.aramkit_augment_dir == cfg.data_dir / "aramkit" / "aram_augments" / "all"
        assert cfg.aramkit_resources_dir == cfg.data_dir / "aramkit" / "resources"
        assert cfg.champion_dir == cfg.data_dir / "ddragon" / "champions"
        assert cfg.trans_file == cfg.data_dir / "augment_trans.json"
        assert cfg.i18n_file == cfg.data_dir / "champions-names-i18n.json"
        assert cfg.augment_desc_file == cfg.data_dir / "aram-mayhem-augments.zh_cn.json"
        assert cfg.log_dir == cfg.project_root / "logs"

    def test_data_source_dataclass_shape(self) -> None:
        assert DataSourceConfig(source="opgg").source == "opgg"


class TestGetConfig:
    def test_returns_cached_singleton(self) -> None:
        assert get_config() is get_config()
        assert get_config().config_path.exists()

    def test_legacy_config_delegates_to_singleton(self) -> None:
        from aram_mayhem_helper.utils.config import config

        app = get_config()
        assert config.data_path == app.data_dir
        assert config.get("crawler", "timeout") == app.crawler.timeout
        assert config.get("suggest", "shrinkage_tau_factor") == app.suggest.shrinkage_tau_factor
        assert config.get("data_source", "source") == app.data_source.source
        assert config.get("missing", "key", default="dflt") == "dflt"

    def test_legacy_data_path_stays_writable(self, tmp_path, monkeypatch) -> None:
        # 旧调用方与测试依赖可变 data_path
        from aram_mayhem_helper.utils.config import config

        monkeypatch.setattr(config, "data_path", tmp_path / "data")
        assert config.data_path == tmp_path / "data"
