"""爬虫行为锁定测试（stub session 与 fixture 数据，不发起真实网络请求）。"""

import json
import time

import pytest
import requests

import aram_mayhem_helper.crawlers.aramkit.aramkit_crawler as aramkit_mod
import aram_mayhem_helper.crawlers.opgg.aram_augment_crawler as opgg_mod
from aram_mayhem_helper.crawlers.aramkit.aramkit_crawler import AramkitCrawler
from aram_mayhem_helper.crawlers.ddragon.champion_crawler import ChampionCrawler
from aram_mayhem_helper.crawlers.opgg.aram_augment_crawler import AramAugmentCrawler


class FakeResponse:
    def __init__(
        self,
        payload: dict | None = None,
        text: str = "",
        error: Exception | None = None,
        json_error: bool = False,
    ) -> None:
        self._payload = payload
        self._text = text
        self._error = error
        self._json_error = json_error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> dict:
        if self._json_error:
            raise json.JSONDecodeError("bad json", "doc", 0)
        return self._payload

    @property
    def text(self) -> str:
        return self._text


class FakeSession:
    """记录调用并返回预设响应的 requests.Session stub。"""

    def __init__(self, responses: dict[str, FakeResponse] | None = None, default: FakeResponse | None = None):
        self.responses = responses or {}
        self.default = default or FakeResponse(payload={})
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.get(url, self.default)


@pytest.fixture
def crawler_env(monkeypatch: pytest.MonkeyPatch, app_config, game_data):
    """爬虫测试环境：fixture AppConfig + get_game_data 注入。"""
    monkeypatch.setattr(opgg_mod, "get_game_data", lambda: game_data)
    monkeypatch.setattr(aramkit_mod, "get_game_data", lambda: game_data)
    return app_config


def _make_opgg_crawler(crawler_env, monkeypatch) -> AramAugmentCrawler:
    crawler = AramAugmentCrawler(config=crawler_env)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    return crawler


class TestFetchJson:
    def test_success_returns_payload(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        crawler.session = FakeSession(responses={"http://x": FakeResponse(payload={"ok": 1})})
        assert crawler.fetch_json("http://x") == {"ok": 1}

    def test_json_decode_error_returns_none(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        crawler.session = FakeSession(responses={"http://x": FakeResponse(payload={}, json_error=True)})
        assert crawler.fetch_json("http://x") is None

    def test_http_error_returns_none(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        crawler.session = FakeSession(responses={"http://x": FakeResponse(payload={}, error=requests.HTTPError("404"))})
        assert crawler.fetch_json("http://x") is None

    def test_request_exception_is_swallowed_inside(self, crawler_env, monkeypatch) -> None:
        # 特征锁定：fetch_json 内部捕获异常返回 None，重试装饰器因此不生效（仅 1 次调用）
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        session = FakeSession()
        session.default = FakeResponse(payload={}, error=requests.ConnectionError("down"))
        crawler.session = session
        assert crawler.fetch_json("http://x") is None
        assert len(session.calls) == 1


class TestSaveToFile:
    def test_writes_json(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        assert crawler.save_to_file({"a": 1}, "42") is True
        saved = json.loads((crawler_env.data_dir / "opgg" / "aram_augments" / "42.json").read_text(encoding="utf-8"))
        assert saved == {"a": 1}


class TestCrawlAndSave:
    def test_success_chain(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        crawler.session = FakeSession(responses={"http://x": FakeResponse(payload={"a": 1})})
        assert crawler.crawl_and_save("http://x", "42") is True

    def test_fetch_failure_returns_false(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        crawler.session = FakeSession(responses={"http://x": FakeResponse(payload={}, json_error=True)})
        assert crawler.crawl_and_save("http://x", "42") is False


class TestBatchCrawl:
    def test_crawls_fixture_champions(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        session = FakeSession()
        crawler.session = session
        results = crawler.batch_crawl(1, 999)
        # fixture 3 英雄（22/103/266）全部成功
        assert results == {"22": True, "103": True, "266": True}
        assert len(session.calls) == 3
        url = session.calls[0][0]
        assert url.startswith("https://lol-api-champion.op.gg/api/contents/stats/champions/")
        assert session.calls[0][1] == {"params": None, "timeout": crawler.timeout}

    def test_stops_after_10_consecutive_failures(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        crawler.session = FakeSession(default=FakeResponse(payload={}, json_error=True))
        results = crawler.batch_crawl(1, 999)
        assert all(v is False for v in results.values())
        assert len(results) == 3  # fixture 仅 3 英雄，未到 10 次


class TestAramkitCrawler:
    def _make(self, crawler_env, monkeypatch) -> AramkitCrawler:
        crawler = AramkitCrawler(config=crawler_env)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        return crawler

    def test_discover_versions_from_html(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        html = (
            '<script src="/assets/data/16.14-20260701-111111111111.js"></script>'
            '<script src="/assets/data/16.15-20260805-7e30d3443ba1.js"></script>'
            '<link href="/assets/resources/16.15-459bb2367aac.css">'
            '<link href="/assets/resources/16.14-123456789012.css">'
        )
        monkeypatch.setattr(crawler, "fetch_text", lambda url: html)
        assert crawler.discover_versions() == ("16.15-20260805-7e30d3443ba1", "16.15-459bb2367aac")
        cached = json.loads((crawler_env.data_dir / "aramkit" / "version.json").read_text(encoding="utf-8"))
        assert cached["data_version"] == "16.15-20260805-7e30d3443ba1"

    def test_discover_versions_falls_back_to_cache(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        (crawler_env.data_dir / "aramkit").mkdir(exist_ok=True)
        (crawler_env.data_dir / "aramkit" / "version.json").write_text(
            json.dumps({"data_version": "16.0.1-abc", "resources_version": "16.0.1-xyz"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(crawler, "fetch_text", lambda url: None)
        assert crawler.discover_versions() == ("16.0.1-abc", "16.0.1-xyz")

    def test_discover_versions_raises_without_source(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: None)
        with pytest.raises(RuntimeError, match="无法发现 aramkit 数据版本"):
            crawler.discover_versions()

    def test_fetch_resources_saves_to_version_dir(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        crawler.fetch_json = lambda url: {"1001": {"name": "泰坦的坚决"}}  # type: ignore[method-assign]
        crawler.fetch_resources("16.0.1-abc123456789")
        aug_file = crawler_env.data_dir / "aramkit" / "resources" / "16.0.1-abc123456789" / "augments.json"
        assert json.loads(aug_file.read_text(encoding="utf-8")) == {"1001": {"name": "泰坦的坚决"}}

    def test_crawl_sets_data_version_and_uses_it(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        crawler.fetch_text = lambda url: (  # type: ignore[method-assign]
            '<script src="/assets/data/16.15-20260801-aaaaaaaaaaaa.js"></script>'
            '<link href="/assets/resources/16.15-abc123456789.css">'
        )
        calls: list[str] = []
        crawler.fetch_json = lambda url: calls.append(url) or {"a": 1}  # type: ignore[method-assign]
        crawler.batch_crawl = lambda start_id, end_id: {"22": True, "103": True, "266": True}  # type: ignore[method-assign]
        assert crawler.crawl(1, 999) is True
        # 版本发现结果保存到实例并被资源 URL 使用
        assert crawler.data_version == "16.15-20260801-aaaaaaaaaaaa"
        assert any("16.15-abc123456789/zh-CN/resources/augments.json" in u for u in calls)

    def test_crawl_empty_results_returns_false(self, crawler_env, monkeypatch) -> None:
        # 英雄数据未抓取时结果为空：all({}) 恒为 True 会误报「全部成功」，需显式判空
        crawler = self._make(crawler_env, monkeypatch)
        crawler.fetch_text = lambda url: (  # type: ignore[method-assign]
            '<script src="/assets/data/16.15-20260801-aaaaaaaaaaaa.js"></script>'
            '<link href="/assets/resources/16.15-abc123456789.css">'
        )
        crawler.fetch_json = lambda url: {"a": 1}  # type: ignore[method-assign]
        crawler.batch_crawl = lambda start_id, end_id: {}  # type: ignore[method-assign]
        assert crawler.crawl(1, 999) is False


class TestChampionCrawler:
    def test_crawl_fetches_latest_version(self, crawler_env, monkeypatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda s: None)
        crawler = ChampionCrawler(config=crawler_env)
        crawler.fetch_json = lambda url, params=None: {"data": {}}  # type: ignore[method-assign]
        crawler.get_latest_ddragon_version = lambda: "16.9.9"  # type: ignore[method-assign]
        assert crawler.crawl() is True
        saved = json.loads((crawler_env.data_dir / "ddragon" / "champions" / "16.9.9.json").read_text(encoding="utf-8"))
        assert saved == {"data": {}}
