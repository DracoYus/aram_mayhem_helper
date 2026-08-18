"""utils.config 配置加载行为测试（TOML → 冻结数据类、拼写回退、env 注入）。"""

from pathlib import Path

import pytest

from aram_mayhem_helper.utils.config import (
    AppConfig,
    DataSourceConfig,
    _rewrite_data_source_text,
    get_config,
    load_config,
    set_data_source,
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
        assert cfg.ocr.debug_save_captures is False  # [ocr] 段缺失时默认关闭

    def test_ocr_debug_save_captures_parsed(self, tmp_path) -> None:
        content = MINIMAL_TOML + "\n[ocr]\ndebug_save_captures = true\n"
        cfg = load_config(config_path=_write_config(tmp_path, content))
        assert cfg.ocr.debug_save_captures is True

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
        assert cfg.ocr_failure_dir == cfg.log_dir / "ocr_failures"
        assert cfg.ocr_debug_dir == cfg.log_dir / "ocr_debug"

    def test_data_source_dataclass_shape(self) -> None:
        assert DataSourceConfig(source="opgg").source == "opgg"


class TestGetConfig:
    def test_returns_cached_singleton(self) -> None:
        assert get_config() is get_config()
        assert get_config().config_path.exists()


@pytest.fixture
def patched_singleton(tmp_path, monkeypatch) -> AppConfig:
    """将 _config_singleton 指向 tmp 配置；teardown 时 monkeypatch 自动恢复原值。"""
    config_path = _write_config(tmp_path)
    cfg = load_config(config_path=config_path)
    monkeypatch.setattr("aram_mayhem_helper.utils.config._config_singleton", cfg)
    return cfg


class TestRewriteDataSourceText:
    """手术式文本编辑纯函数：只动 [data_source] 段内 source 行，保留其余一切。"""

    def test_replaces_only_in_data_source_section(self) -> None:
        content = '[crawler.opgg.aram_augment]\nsource = "opgg"\n\n[data_source]\nsource = "aramkit"\n'
        result = _rewrite_data_source_text(content, "opgg")
        # 其他段内同名键不动，仅 [data_source] 段被替换
        assert result == ('[crawler.opgg.aram_augment]\nsource = "opgg"\n\n[data_source]\nsource = "opgg"\n')

    def test_preserves_comments_and_line_endings(self) -> None:
        content = (
            '# 推荐引擎/GUI/网页默认数据源: "opgg" | "aramkit"\n'
            "[data_source]\n"
            "# 行内注释\n"
            'source = "aramkit"  # 默认\n'
            "\n"
            "[suggest]\n"
            "shrinkage_tau_factor = 0.5\n"
        )
        result = _rewrite_data_source_text(content, "opgg")
        assert result == (
            '# 推荐引擎/GUI/网页默认数据源: "opgg" | "aramkit"\n'
            "[data_source]\n"
            "# 行内注释\n"
            'source = "opgg"  # 默认\n'
            "\n"
            "[suggest]\n"
            "shrinkage_tau_factor = 0.5\n"
        )

    def test_preserves_crlf_and_trailing_newline(self) -> None:
        content = '[data_source]\r\nsource = "aramkit"\r\n'
        result = _rewrite_data_source_text(content, "opgg")
        assert result == '[data_source]\r\nsource = "opgg"\r\n'

    def test_no_trailing_newline_stays_absent(self) -> None:
        content = '[data_source]\nsource = "aramkit"'
        result = _rewrite_data_source_text(content, "opgg")
        assert result == '[data_source]\nsource = "opgg"'

    def test_single_quotes_normalized_to_double(self) -> None:
        content = "[data_source]\nsource = 'opgg'\n"
        result = _rewrite_data_source_text(content, "aramkit")
        assert result == '[data_source]\nsource = "aramkit"\n'

    def test_section_header_with_spaces_or_quotes(self) -> None:
        # TOML 合法表头变体：[ data_source ] / ["data_source"]，tomllib 可解析
        for header in ("[ data_source ]", '["data_source"]'):
            content = f'{header}\nsource = "aramkit"\n'
            result = _rewrite_data_source_text(content, "opgg")
            assert result == f'{header}\nsource = "opgg"\n'

    def test_unchanged_value_returns_original(self) -> None:
        content = '[data_source]\nsource = "aramkit"\n'
        assert _rewrite_data_source_text(content, "aramkit") is content

    def test_missing_section_raises(self) -> None:
        content = "[suggest]\nshrinkage_tau_factor = 0.5\n"
        with pytest.raises(ValueError, match="data_source"):
            _rewrite_data_source_text(content, "opgg")

    def test_missing_source_key_raises(self) -> None:
        content = "[data_source]\nother_key = 1\n"
        with pytest.raises(ValueError, match="source"):
            _rewrite_data_source_text(content, "opgg")


class TestSetDataSource:
    """set_data_source IO 路径：写回、单例重建与失败清理。"""

    def test_writes_and_rebuilds_singleton(self, tmp_path, patched_singleton) -> None:
        old_cfg = patched_singleton
        config_path = old_cfg.config_path

        new_cfg = set_data_source("opgg")

        assert config_path.read_text(encoding="utf-8").count('source = "opgg"') == 1
        assert new_cfg.data_source.source == "opgg"
        assert get_config() is new_cfg  # 单例已重建
        assert get_config() is not old_cfg

    def test_rest_of_file_untouched(self, tmp_path, patched_singleton) -> None:
        old_cfg = patched_singleton
        original = old_cfg.config_path.read_text(encoding="utf-8")

        set_data_source("opgg")
        new_content = old_cfg.config_path.read_text(encoding="utf-8")

        # 除 source 行外逐行字节相同
        changed_lines = [
            (before, after) for before, after in zip(original.splitlines(), new_content.splitlines()) if before != after
        ]
        assert changed_lines == [('source = "aramkit"', 'source = "opgg"')]

    def test_invalid_source_raises_without_write(self, tmp_path, patched_singleton) -> None:
        old_cfg = patched_singleton
        original = old_cfg.config_path.read_text(encoding="utf-8")

        with pytest.raises(ValueError, match="非法数据源"):
            set_data_source("foo")

        assert old_cfg.config_path.read_text(encoding="utf-8") == original
        assert get_config() is old_cfg

    def test_same_value_does_not_write(self, tmp_path, patched_singleton) -> None:
        old_cfg = patched_singleton
        original = old_cfg.config_path.read_text(encoding="utf-8")

        assert set_data_source("aramkit") is old_cfg
        assert old_cfg.config_path.read_text(encoding="utf-8") == original

    def test_write_failure_cleans_tmp_and_keeps_state(self, tmp_path, patched_singleton, monkeypatch) -> None:
        old_cfg = patched_singleton
        original = old_cfg.config_path.read_text(encoding="utf-8")

        def _boom(src: object, dst: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("os.replace", _boom)
        with pytest.raises(OSError):
            set_data_source("opgg")

        assert old_cfg.config_path.read_text(encoding="utf-8") == original
        assert not old_cfg.config_path.with_name(old_cfg.config_path.name + ".tmp").exists()
        assert get_config() is old_cfg

    def test_missing_section_raises_without_write(self, tmp_path, monkeypatch) -> None:
        config_path = _write_config(tmp_path, "[suggest]\nshrinkage_tau_factor = 0.5\n")
        cfg = load_config(config_path=config_path)
        monkeypatch.setattr("aram_mayhem_helper.utils.config._config_singleton", cfg)
        original = config_path.read_text(encoding="utf-8")

        with pytest.raises(ValueError, match="data_source"):
            set_data_source("aramkit")  # load_config 对缺失段默认 opgg，须用不同值绕过早退

        assert config_path.read_text(encoding="utf-8") == original
        assert get_config() is cfg

    def test_crlf_round_trip_via_io(self, tmp_path, monkeypatch) -> None:
        # CRLF 文件经真实磁盘往返后保持 CRLF（newline="" 显式读写，不依赖平台换行翻译）
        crlf_content = '[data_source]\r\nsource = "aramkit"\r\n'
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "config.toml"
        config_path.write_text(crlf_content, encoding="utf-8", newline="")
        cfg = load_config(config_path=config_path)
        monkeypatch.setattr("aram_mayhem_helper.utils.config._config_singleton", cfg)

        set_data_source("opgg")
        assert config_path.read_bytes() == '[data_source]\r\nsource = "opgg"\r\n'.encode("utf-8")

    def test_read_failure_raises_without_write(self, tmp_path, patched_singleton) -> None:
        old_cfg = patched_singleton
        old_cfg.config_path.unlink()  # 文件缺失 → open() 抛 FileNotFoundError(OSError)

        with pytest.raises(OSError):
            set_data_source("opgg")

        assert get_config() is old_cfg  # 单例未重建
        assert not old_cfg.config_path.with_name(old_cfg.config_path.name + ".tmp").exists()
