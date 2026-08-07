"""cli 参数解析与分发行为测试。"""

import sys

import pytest

import aram_mayhem_helper.cli as cli
from aram_mayhem_helper.cli import parse_args


def _parse(monkeypatch: pytest.MonkeyPatch, argv: list[str]):
    monkeypatch.setattr(sys, "argv", ["prog", *argv])
    return parse_args()


class TestParseArgs:
    def test_recommend_command(self, monkeypatch) -> None:
        assert _parse(monkeypatch, ["recommend"]).command == "recommend"

    def test_main_alias_maps_to_main_command(self, monkeypatch) -> None:
        assert _parse(monkeypatch, ["main"]).command == "main"

    def test_aram_augment_crawler_defaults(self, monkeypatch) -> None:
        args = _parse(monkeypatch, ["aram-augment-crawler"])
        assert args.command == "aram-augment-crawler"
        assert args.start_page == 1
        assert args.end_page == 999

    def test_aram_augment_crawler_custom_range(self, monkeypatch) -> None:
        args = _parse(monkeypatch, ["aram-augment-crawler", "--start-page", "5", "--end-page", "10"])
        assert (args.start_page, args.end_page) == (5, 10)

    def test_champion_crawler(self, monkeypatch) -> None:
        assert _parse(monkeypatch, ["champion-crawler"]).command == "champion-crawler"

    def test_aramkit_crawler_dataset_choices(self, monkeypatch) -> None:
        args = _parse(monkeypatch, ["aramkit-crawler", "--dataset", "high"])
        assert args.command == "aramkit-crawler"
        assert args.dataset == "high"
        with pytest.raises(SystemExit):
            _parse(monkeypatch, ["aramkit-crawler", "--dataset", "invalid"])

    def test_web_defaults(self, monkeypatch) -> None:
        args = _parse(monkeypatch, ["web"])
        assert args.command == "web"
        assert (args.host, args.port) == ("127.0.0.1", 5000)

    def test_web_custom_host_port(self, monkeypatch) -> None:
        args = _parse(monkeypatch, ["web", "--host", "0.0.0.0", "--port", "8000"])
        assert (args.host, args.port) == ("0.0.0.0", 8000)

    def test_no_command_returns_none(self, monkeypatch) -> None:
        assert _parse(monkeypatch, []).command is None


class TestCliMain:
    def _stub(self, monkeypatch: pytest.MonkeyPatch, **handlers) -> None:
        monkeypatch.setattr(cli, "setup_logging", lambda: None)
        for name, handler in handlers.items():
            monkeypatch.setattr(cli, name, handler)

    def test_no_command_defaults_to_recommend(self, monkeypatch) -> None:
        called = []
        self._stub(monkeypatch, recommend=lambda: called.append("recommend"))
        assert cli.cli_main([]) == 0
        assert called == ["recommend"]

    def test_routes_recommend_command(self, monkeypatch) -> None:
        called = []
        self._stub(monkeypatch, recommend=lambda: called.append("recommend"))
        assert cli.cli_main(["recommend"]) == 0
        assert called == ["recommend"]

    def test_routes_main_alias(self, monkeypatch) -> None:
        called = []
        self._stub(monkeypatch, recommend=lambda: called.append("recommend"))
        assert cli.cli_main(["main"]) == 0
        assert called == ["recommend"]

    def test_routes_aram_augment_crawler(self, monkeypatch) -> None:
        called = []
        self._stub(
            monkeypatch,
            aram_augment_crawler=lambda start_page, end_page: called.append((start_page, end_page)),
        )
        assert cli.cli_main(["aram-augment-crawler", "--start-page", "3"]) == 0
        assert called == [(3, 999)]

    def test_routes_champion_crawler(self, monkeypatch) -> None:
        called = []
        self._stub(monkeypatch, champion_crawler=lambda: called.append(True))
        assert cli.cli_main(["champion-crawler"]) == 0
        assert called == [True]

    def test_routes_aramkit_crawler(self, monkeypatch) -> None:
        called = []
        self._stub(
            monkeypatch,
            aramkit_crawler=lambda start_id, end_id, dataset: called.append((start_id, end_id, dataset)),
        )
        assert cli.cli_main(["aramkit-crawler", "--start-id", "5", "--dataset", "high"]) == 0
        assert called == [(5, 999, "high")]

    def test_routes_web_with_host_port(self, monkeypatch) -> None:
        class FakeApp:
            def __init__(self) -> None:
                self.kwargs = None

            def run(self, **kwargs) -> None:
                self.kwargs = kwargs

        fake_app = FakeApp()
        monkeypatch.setattr("aram_mayhem_helper.web.create_app", lambda: fake_app)
        self._stub(monkeypatch)
        assert cli.cli_main(["web", "--host", "0.0.0.0", "--port", "8000"]) == 0
        assert fake_app.kwargs == {"host": "0.0.0.0", "port": 8000, "debug": False}


class TestRecommend:
    def test_no_game_returns_gracefully(self, monkeypatch) -> None:
        monkeypatch.setattr(cli, "get_current_champion_name", lambda: None)
        cli.recommend()  # 不应抛异常

    def test_error_is_caught_and_logged(self, monkeypatch) -> None:
        def boom() -> str:
            raise RuntimeError("game client exploded")

        monkeypatch.setattr(cli, "get_current_champion_name", boom)
        cli.recommend()  # 不应向上传播异常

    def test_falls_back_to_opgg_when_aramkit_missing(
        self, monkeypatch, game_data, app_config
    ) -> None:
        """默认源(aramkit)缺数据时回退 opgg 并传给 Suggest（修复推荐硬中断）。"""
        calls: list[tuple[str, str | None]] = []
        captured_ocr: list[list[str]] = []

        class _FakeSuggest:
            def __init__(self, champion_id: str, data, *, source=None, thresholds=None) -> None:
                calls.append((champion_id, source))

            def suggest(self, augments: list[str]) -> list[str]:
                return ["快选符文：泰坦的坚决，别的不用看了"]

        class _FakeOcr:
            def get_augments(self) -> list[str]:
                captured_ocr.append(["泰坦的坚决"])
                return captured_ocr[-1]

        monkeypatch.setattr(cli, "get_current_champion_name", lambda: "Ashe")  # fixture: 22
        monkeypatch.setattr(cli, "get_game_data", lambda: game_data)
        monkeypatch.setattr(cli, "get_config", lambda: app_config)
        monkeypatch.setattr(cli, "Suggest", _FakeSuggest)
        monkeypatch.setattr(cli, "get_ocr_tool", lambda: _FakeOcr())
        cli.recommend()
        # 22 无 aramkit fixture → 回退 opgg
        assert calls == [("22", "opgg")]
        assert captured_ocr == [["泰坦的坚决"]]

    def test_no_data_in_either_source_returns_gracefully(
        self, monkeypatch, game_data, app_config, caplog
    ) -> None:
        """266 在 opgg/aramkit 均无数据 → 记录错误并返回，不调用 Suggest/OCR。"""
        calls: list[tuple[str, str | None]] = []

        class _FakeSuggest:
            def __init__(self, champion_id: str, data, *, source=None, thresholds=None) -> None:
                calls.append((champion_id, source))

        monkeypatch.setattr(cli, "get_current_champion_name", lambda: "Aatrox")  # fixture: 266
        monkeypatch.setattr(cli, "get_game_data", lambda: game_data)
        monkeypatch.setattr(cli, "get_config", lambda: app_config)
        monkeypatch.setattr(cli, "Suggest", _FakeSuggest)
        with caplog.at_level("ERROR", logger="aram_mayhem_helper.cli"):
            cli.recommend()
        assert calls == []
        assert any("都没有符文数据" in r.message for r in caplog.records)
