"""cli 参数解析行为锁定测试（当前 parse_args 读取 sys.argv）。"""

import sys

import pytest

from aram_mayhem_helper.cli import parse_args


def _parse(monkeypatch: pytest.MonkeyPatch, argv: list[str]):
    monkeypatch.setattr(sys, "argv", ["prog", *argv])
    return parse_args()


class TestParseArgs:
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

    def test_main_command(self, monkeypatch) -> None:
        assert _parse(monkeypatch, ["main"]).command == "main"

    def test_web_defaults(self, monkeypatch) -> None:
        args = _parse(monkeypatch, ["web"])
        assert args.command == "web"
        assert (args.host, args.port) == ("127.0.0.1", 5000)

    def test_web_custom_host_port(self, monkeypatch) -> None:
        args = _parse(monkeypatch, ["web", "--host", "0.0.0.0", "--port", "8000"])
        assert (args.host, args.port) == ("0.0.0.0", 8000)

    def test_no_command_returns_none(self, monkeypatch) -> None:
        assert _parse(monkeypatch, []).command is None
