"""共享推荐流程（recommend_flow.run_recommend）行为测试。

覆盖原 CLI 内联实现的行为（数据源回退、双源无数据、异常吞掉），
以及 GUI 显式数据源传参语义。
"""

from typing import Any

import pytest

import aram_mayhem_helper.algorithm.recommend_flow as recommend_flow
from aram_mayhem_helper.algorithm.recommend_flow import run_recommend


class FakeOcr:
    def __init__(self, augments: list[str] | Exception) -> None:
        self._augments = augments
        self.calls = 0

    def get_augments(self) -> list[str]:
        self.calls += 1
        if isinstance(self._augments, Exception):
            raise self._augments
        return self._augments


class FakeSuggest:
    """记录构造参数的 Suggest 替身（按模块名 patch）。"""

    init_args: Any = None
    suggest_return: list[str] = []
    suggest_raises: Exception | None = None

    def __init__(self, champion_id: str, data: Any, *, source: Any = None, thresholds: Any = None) -> None:
        type(self).init_args = (champion_id, source)

    def suggest(self, augments: list[str], *, on_unrecognized: Any = None) -> list[str]:
        if type(self).suggest_raises is not None:
            raise type(self).suggest_raises
        return type(self).suggest_return


@pytest.fixture
def fake_suggest(monkeypatch: pytest.MonkeyPatch) -> type[FakeSuggest]:
    monkeypatch.setattr(recommend_flow, "Suggest", FakeSuggest)
    FakeSuggest.init_args = None
    FakeSuggest.suggest_return = []
    FakeSuggest.suggest_raises = None
    return FakeSuggest


class TestRecommendFlow:
    def test_full_flow_returns_lines(self, monkeypatch, game_data, fake_suggest) -> None:
        monkeypatch.setattr(recommend_flow, "get_current_champion_name", lambda: "Ahri")  # fixture: 103
        fake_suggest.suggest_return = ["快选符文：泰坦的坚决"]
        ocr = FakeOcr(["泰坦的坚决"])

        outcome = run_recommend(game_data, ocr, preferred_source="aramkit")

        assert outcome.lines == ["快选符文：泰坦的坚决"]
        assert outcome.champion_name == "Ahri"
        assert outcome.source == "aramkit"
        assert fake_suggest.init_args == ("103", "aramkit")
        assert ocr.calls == 1

    def test_falls_back_to_opgg_when_aramkit_missing(self, monkeypatch, game_data, fake_suggest) -> None:
        """默认/首选源缺数据时回退另一源并传给 Suggest（修复推荐硬中断）。"""
        monkeypatch.setattr(recommend_flow, "get_current_champion_name", lambda: "Ashe")  # fixture: 22
        ocr = FakeOcr(["泰坦的坚决"])

        outcome = run_recommend(game_data, ocr, preferred_source="aramkit")

        # 22 无 aramkit fixture → 回退 opgg
        assert fake_suggest.init_args == ("22", "opgg")
        assert outcome.source == "opgg"

    def test_no_preferred_source_uses_config_default(self, monkeypatch, game_data, fake_suggest) -> None:
        monkeypatch.setattr(recommend_flow, "get_current_champion_name", lambda: "Ahri")
        run_recommend(game_data, FakeOcr([]))
        assert fake_suggest.init_args == ("103", game_data.default_source())

    def test_no_game_returns_empty(self, monkeypatch, game_data, fake_suggest) -> None:
        monkeypatch.setattr(recommend_flow, "get_current_champion_name", lambda: None)
        outcome = run_recommend(game_data, FakeOcr([]))
        assert outcome.lines == []
        assert outcome.champion_name is None
        assert fake_suggest.init_args is None  # Suggest 未被构造

    def test_unknown_champion_returns_empty(self, monkeypatch, game_data, fake_suggest) -> None:
        monkeypatch.setattr(recommend_flow, "get_current_champion_name", lambda: "不存在英雄")
        outcome = run_recommend(game_data, FakeOcr([]))
        assert outcome.lines == []
        assert fake_suggest.init_args is None

    def test_no_data_in_either_source_returns_empty(self, monkeypatch, game_data, fake_suggest) -> None:
        """266 在 opgg/aramkit 均无数据 → 返回空结果，不构造 Suggest、不调 OCR。"""
        monkeypatch.setattr(recommend_flow, "get_current_champion_name", lambda: "Aatrox")  # fixture: 266
        ocr = FakeOcr([])
        outcome = run_recommend(game_data, ocr)
        assert outcome.lines == []
        assert fake_suggest.init_args is None
        assert ocr.calls == 0

    def test_live_client_exception_swallowed(self, monkeypatch, game_data, fake_suggest) -> None:
        def boom() -> str:
            raise RuntimeError("game client exploded")

        monkeypatch.setattr(recommend_flow, "get_current_champion_name", boom)
        outcome = run_recommend(game_data, FakeOcr([]))
        assert outcome.lines == []  # 不向上传播异常

    def test_ocr_exception_swallowed(self, monkeypatch, game_data, fake_suggest) -> None:
        monkeypatch.setattr(recommend_flow, "get_current_champion_name", lambda: "Ahri")
        outcome = run_recommend(game_data, FakeOcr(RuntimeError("ocr down")))
        assert outcome.lines == []
        assert outcome.champion_name == "Ahri"

    def test_suggest_exception_swallowed(self, monkeypatch, game_data, fake_suggest) -> None:
        monkeypatch.setattr(recommend_flow, "get_current_champion_name", lambda: "Ahri")
        fake_suggest.suggest_raises = RuntimeError("match failed")
        outcome = run_recommend(game_data, FakeOcr(["泰坦的坚决"]))
        assert outcome.lines == []

    def test_on_unrecognized_passed_through(self, monkeypatch, game_data, fake_suggest) -> None:
        monkeypatch.setattr(recommend_flow, "get_current_champion_name", lambda: "Ahri")
        received: list[tuple[str, int]] = []

        class RecordingSuggest(FakeSuggest):
            def suggest(self, augments: list[str], *, on_unrecognized: Any = None) -> list[str]:
                received.append(("called", len(augments)))
                assert on_unrecognized is not None
                return []

        monkeypatch.setattr(recommend_flow, "Suggest", RecordingSuggest)
        run_recommend(game_data, FakeOcr(["未知符文"]))
        assert received == [("called", 1)]

    def test_no_unrecognized_lines_logged(self, monkeypatch, game_data, fake_suggest, caplog) -> None:
        monkeypatch.setattr(recommend_flow, "get_current_champion_name", lambda: "Ahri")
        fake_suggest.suggest_return = []
        with caplog.at_level("WARNING", logger="aram_mayhem_helper.algorithm.recommend_flow"):
            run_recommend(game_data, FakeOcr([]))
        assert any("未能生成任何符文建议" in r.message for r in caplog.records)
