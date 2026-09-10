"""爬虫行为锁定测试（stub session 与 fixture 数据，不发起真实网络请求）。"""

import json
import time
from types import SimpleNamespace
from typing import Any

import pytest
import requests

import aram_mayhem_helper.crawlers.aramkit.aramkit_crawler as aramkit_mod
import aram_mayhem_helper.crawlers.opgg.aram_augment_crawler as opgg_mod
from aram_mayhem_helper.crawlers.aramkit.aramkit_crawler import AramkitCrawler
from aram_mayhem_helper.crawlers.ddragon.champion_crawler import ChampionCrawler, DDragon_VERSIONS_URL
from aram_mayhem_helper.crawlers.opgg.aram_augment_crawler import AramAugmentCrawler


class FakeResponse:
    def __init__(
        self,
        payload: Any = None,
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

    def json(self) -> Any:
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

    def test_http_error_retries_before_returning_none(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        session = FakeSession(responses={"http://x": FakeResponse(payload={}, error=requests.HTTPError("404"))})
        crawler.session = session

        assert crawler.fetch_json("http://x") is None
        assert len(session.calls) == 4

    def test_request_exception_retries_until_success(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        session = FakeSession()
        responses = iter(
            [
                FakeResponse(error=requests.ConnectionError("down")),
                FakeResponse(error=requests.Timeout("slow")),
                FakeResponse(payload={"ok": 1}),
            ]
        )

        def get(url: str, **kwargs):
            session.calls.append((url, kwargs))
            return next(responses)

        monkeypatch.setattr(session, "get", get)
        crawler.session = session

        assert crawler.fetch_json("http://x") == {"ok": 1}
        assert len(session.calls) == 3


class TestSaveToFile:
    def test_writes_json(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        assert crawler.save_to_file({"a": 1}, "42") is True
        saved = json.loads((crawler_env.data_dir / "opgg" / "aram_augments" / "42.json").read_text(encoding="utf-8"))
        assert saved == {"a": 1}

    def test_failed_write_keeps_existing_file(self, crawler_env, monkeypatch) -> None:
        crawler = _make_opgg_crawler(crawler_env, monkeypatch)
        target = crawler_env.data_dir / "opgg" / "aram_augments" / "42.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"old": true}', encoding="utf-8")

        assert crawler.save_to_file({"bad": object()}, "42") is False
        assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
        assert not (target.parent / ".42.json.tmp").exists()


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
    # 首页 HTML 模板：同时包含数据版本与资源版本
    HTML_TEMPLATE = (
        '<script src="/assets/data/{data_version}.js"></script><link href="/assets/resources/{resources_version}.css">'
    )
    DATA_VERSION = "16.15-20260801-aaaaaaaaaaaa"
    RESOURCES_VERSION = "16.15-abc123456789"

    def test_fetch_text_retries_before_returning_none(self, crawler_env, monkeypatch) -> None:
        crawler = AramkitCrawler(config=crawler_env)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        session = FakeSession(default=FakeResponse(error=requests.ConnectionError("down")))
        crawler.session = session

        assert crawler.fetch_text("http://x") is None
        assert len(session.calls) == 4

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

    # ---- 服务器无更新跳过（version.json crawled 记录）----

    def _html(self) -> str:
        return self.HTML_TEMPLATE.format(data_version=self.DATA_VERSION, resources_version=self.RESOURCES_VERSION)

    def _write_version_state(
        self,
        crawler: AramkitCrawler,
        data_version: str,
        resources_version: str,
        crawled: Any = None,
        progress: Any = None,
    ) -> None:
        """写入合成的版本状态文件。"""
        state = {"data_version": data_version, "resources_version": resources_version}
        if crawled is not None:
            state["crawled"] = crawled
        if progress is not None:
            state["progress"] = progress
        crawler.version_file.parent.mkdir(parents=True, exist_ok=True)
        crawler.version_file.write_text(json.dumps(state), encoding="utf-8")

    def _read_version_state(self, crawler: AramkitCrawler) -> dict[str, Any]:
        return json.loads(crawler.version_file.read_text(encoding="utf-8"))

    def _make_resources_exist(self, crawler_env, crawler: AramkitCrawler) -> None:
        """预创建完整的资源文件（augments + champions）。"""
        res_dir = crawler_env.data_dir / "aramkit" / "resources" / self.RESOURCES_VERSION
        res_dir.mkdir(parents=True, exist_ok=True)
        (res_dir / "augments.json").write_text("{}", encoding="utf-8")
        (res_dir / "champions.json").write_text("{}", encoding="utf-8")

    def _unexpected(self, *args, **kwargs) -> Any:
        raise AssertionError("不应发起该请求")

    def test_crawl_skips_when_server_data_unchanged(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        self._write_version_state(
            crawler,
            self.DATA_VERSION,
            self.RESOURCES_VERSION,
            crawled={crawler.dataset: {"start_id": 1, "end_id": 999}},
        )
        self._make_resources_exist(crawler_env, crawler)
        monkeypatch.setattr(crawler, "batch_crawl", self._unexpected)  # type: ignore[method-assign]
        monkeypatch.setattr(crawler, "fetch_json", self._unexpected)  # type: ignore[method-assign]
        assert crawler.crawl(1, 999) is True

    def test_crawl_refreshes_missing_resources_before_skipping_unchanged_data(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        self._write_version_state(
            crawler,
            self.DATA_VERSION,
            self.RESOURCES_VERSION,
            crawled={crawler.dataset: {"start_id": 1, "end_id": 999}},
        )
        resource_calls: list[str] = []
        monkeypatch.setattr(
            crawler,
            "fetch_json",
            lambda url: resource_calls.append(url) or {},
        )
        monkeypatch.setattr(crawler, "batch_crawl", self._unexpected)  # type: ignore[method-assign]

        assert crawler.crawl(1, 999) is True
        assert resource_calls == [
            f"{crawler.resources_base_url}{self.RESOURCES_VERSION}/{crawler.language}/resources/augments.json",
            f"{crawler.resources_base_url}{self.RESOURCES_VERSION}/{crawler.language}/resources/champions.json",
        ]

    def test_crawl_persists_completed_ids_after_partial_failure(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        self._make_resources_exist(crawler_env, crawler)
        attempts: list[str] = []
        outcomes = {"22": True, "103": False, "266": False}

        def crawl_and_save(url: str, filename: str, params=None) -> bool:
            attempts.append(filename)
            return outcomes[filename]

        monkeypatch.setattr(crawler, "crawl_and_save", crawl_and_save)

        assert crawler.crawl(1, 999) is False
        assert attempts == ["22", "103", "266"]
        state = self._read_version_state(crawler)
        assert state["progress"][crawler.dataset] == {
            "data_version": self.DATA_VERSION,
            "start_id": 1,
            "end_id": 999,
            "completed_ids": [22],
        }
        assert state["crawled"] == {}

    def test_crawl_keeps_progress_when_interrupted(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        self._make_resources_exist(crawler_env, crawler)
        attempts: list[str] = []

        def crawl_and_save(url: str, filename: str, params=None) -> bool:
            attempts.append(filename)
            if filename == "103":
                raise KeyboardInterrupt
            return True

        monkeypatch.setattr(crawler, "crawl_and_save", crawl_and_save)

        with pytest.raises(KeyboardInterrupt):
            crawler.crawl(1, 999)
        assert attempts == ["22", "103"]
        state = self._read_version_state(crawler)
        assert state["progress"][crawler.dataset]["completed_ids"] == [22]
        assert state["crawled"] == {}

    def test_crawl_resumes_from_completed_ids(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        self._make_resources_exist(crawler_env, crawler)
        self._write_version_state(
            crawler,
            self.DATA_VERSION,
            self.RESOURCES_VERSION,
            progress={
                crawler.dataset: {
                    "data_version": self.DATA_VERSION,
                    "start_id": 1,
                    "end_id": 999,
                    "completed_ids": [22],
                }
            },
        )
        attempts: list[str] = []
        monkeypatch.setattr(
            crawler,
            "crawl_and_save",
            lambda url, filename, params=None: attempts.append(filename) or True,
        )

        assert crawler.crawl(1, 999) is True
        assert attempts == ["103", "266"]
        state = self._read_version_state(crawler)
        assert state["crawled"] == {crawler.dataset: {"start_id": 1, "end_id": 999}}
        assert state["progress"] == {}

    def test_force_crawl_clears_old_marker_before_partial_failure(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        self._make_resources_exist(crawler_env, crawler)
        self._write_version_state(
            crawler,
            self.DATA_VERSION,
            self.RESOURCES_VERSION,
            crawled={crawler.dataset: {"start_id": 1, "end_id": 999}},
            progress={
                crawler.dataset: {
                    "data_version": self.DATA_VERSION,
                    "start_id": 1,
                    "end_id": 999,
                    "completed_ids": [22],
                }
            },
        )
        attempts: list[str] = []
        outcomes = {"22": True, "103": False, "266": False}

        def crawl_and_save(url: str, filename: str, params=None) -> bool:
            attempts.append(filename)
            return outcomes[filename]

        monkeypatch.setattr(crawler, "crawl_and_save", crawl_and_save)

        assert crawler.crawl(1, 999, force=True) is False
        assert attempts == ["22", "103", "266"]
        state = self._read_version_state(crawler)
        assert state["crawled"] == {}
        assert state["progress"][crawler.dataset]["completed_ids"] == [22]

    def test_crawl_crawls_when_server_version_updated(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        new_data_version = "16.16-20260901-bbbbbbbbbbbb"
        html = self.HTML_TEMPLATE.format(data_version=new_data_version, resources_version=self.RESOURCES_VERSION)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: html)
        # 本地记录为旧版本的完整爬取
        self._write_version_state(
            crawler,
            "16.14-20260701-cccccccccccc",
            self.RESOURCES_VERSION,
            crawled={crawler.dataset: {"start_id": 1, "end_id": 999}},
        )
        monkeypatch.setattr(crawler, "fetch_json", lambda url: {})  # type: ignore[method-assign]
        batch_calls: list[tuple[int, int]] = []
        crawler.batch_crawl = lambda start_id, end_id: (
            batch_calls.append((start_id, end_id)),
            {"22": True, "103": True, "266": True},
        )[1]  # type: ignore[method-assign]
        assert crawler.crawl(1, 999) is True
        assert batch_calls == [(1, 999)]
        state = self._read_version_state(crawler)
        assert state["data_version"] == new_data_version
        # 旧版本的爬取记录作废，新版本爬取成功后重新记录
        assert state["crawled"] == {crawler.dataset: {"start_id": 1, "end_id": 999}}

    def test_crawl_crawls_when_recorded_range_differs(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        self._write_version_state(
            crawler,
            self.DATA_VERSION,
            self.RESOURCES_VERSION,
            crawled={crawler.dataset: {"start_id": 1, "end_id": 5}},
        )
        monkeypatch.setattr(crawler, "fetch_json", lambda url: {})  # type: ignore[method-assign]
        batch_calls: list[tuple[int, int]] = []
        crawler.batch_crawl = lambda start_id, end_id: (
            batch_calls.append((start_id, end_id)),
            {"22": True, "103": True, "266": True},
        )[1]  # type: ignore[method-assign]
        assert crawler.crawl(1, 999) is True
        assert batch_calls == [(1, 999)]

    def test_crawl_force_bypasses_unchanged_check(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        self._write_version_state(
            crawler,
            self.DATA_VERSION,
            self.RESOURCES_VERSION,
            crawled={crawler.dataset: {"start_id": 1, "end_id": 999}},
        )
        monkeypatch.setattr(crawler, "fetch_json", lambda url: {})  # type: ignore[method-assign]
        batch_calls: list[tuple[int, int]] = []
        crawler.batch_crawl = lambda start_id, end_id: (
            batch_calls.append((start_id, end_id)),
            {"22": True, "103": True, "266": True},
        )[1]  # type: ignore[method-assign]
        assert crawler.crawl(1, 999, force=True) is True
        assert batch_calls == [(1, 999)]

    def test_crawl_records_crawled_marker_after_full_success(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        monkeypatch.setattr(crawler, "fetch_json", lambda url: {})  # type: ignore[method-assign]
        crawler.batch_crawl = lambda start_id, end_id: {"22": True, "103": True, "266": True}  # type: ignore[method-assign]
        assert crawler.crawl(1, 999) is True
        state = self._read_version_state(crawler)
        assert state["crawled"] == {crawler.dataset: {"start_id": 1, "end_id": 999}}

    def test_crawl_does_not_record_marker_when_batch_failed(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        crawler.session = FakeSession(default=FakeResponse(payload={}, json_error=True))
        assert crawler.crawl(1, 999) is False
        state = self._read_version_state(crawler)
        assert state["crawled"] == {}

    def test_crawl_skips_resource_download_when_files_exist(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        self._make_resources_exist(crawler_env, crawler)
        monkeypatch.setattr(crawler, "fetch_json", self._unexpected)  # type: ignore[method-assign]
        crawler.batch_crawl = lambda start_id, end_id: {"22": True, "103": True, "266": True}  # type: ignore[method-assign]
        assert crawler.crawl(1, 999) is True

    def test_discover_versions_preserves_crawled_for_unchanged_version(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        self._write_version_state(
            crawler,
            self.DATA_VERSION,
            self.RESOURCES_VERSION,
            crawled={crawler.dataset: {"start_id": 1, "end_id": 5}},
        )
        crawler.discover_versions()
        assert self._read_version_state(crawler)["crawled"] == {crawler.dataset: {"start_id": 1, "end_id": 5}}

    def test_discover_versions_drops_crawled_when_version_updated(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        html = self.HTML_TEMPLATE.format(
            data_version="16.16-20260901-bbbbbbbbbbbb", resources_version=self.RESOURCES_VERSION
        )
        monkeypatch.setattr(crawler, "fetch_text", lambda url: html)
        self._write_version_state(
            crawler,
            self.DATA_VERSION,
            self.RESOURCES_VERSION,
            crawled={crawler.dataset: {"start_id": 1, "end_id": 999}},
        )
        crawler.discover_versions()
        assert self._read_version_state(crawler)["crawled"] == {}

    # ---- batch_crawl 连续失败中止 ----

    def _champion_url(self, crawler: AramkitCrawler, champion_id: int) -> str:
        return (
            f"{crawler.data_base_url}{crawler.data_version}/stats/{crawler.dataset}/champion-details/{champion_id}.json"
        )

    def _stub_champion_ids(self, champion_ids: list[int]) -> SimpleNamespace:
        return SimpleNamespace(champion_ids=lambda: [str(champion_id) for champion_id in champion_ids])

    def test_batch_crawl_resets_consecutive_failures_on_success(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        crawler.data_version = self.DATA_VERSION
        champion_ids = list(range(1, 26))
        odd_failures = {champion_id for champion_id in champion_ids if champion_id % 2 == 1}
        monkeypatch.setattr(aramkit_mod, "get_game_data", lambda: self._stub_champion_ids(champion_ids))
        responses = {
            self._champion_url(crawler, cid): FakeResponse(payload={}, json_error=True) for cid in odd_failures
        }
        crawler.session = FakeSession(responses=responses, default=FakeResponse(payload={"ok": 1}))
        results = crawler.batch_crawl(1, 999)
        # 失败分散时不应误中止：全部 25 个英雄都被尝试
        assert len(results) == 25
        assert sorted(int(key) for key, ok in results.items() if not ok) == sorted(odd_failures)

    def test_batch_crawl_aborts_after_10_consecutive_failures(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        crawler.data_version = self.DATA_VERSION
        champion_ids = list(range(1, 26))
        monkeypatch.setattr(aramkit_mod, "get_game_data", lambda: self._stub_champion_ids(champion_ids))
        crawler.session = FakeSession(default=FakeResponse(payload={}, json_error=True))
        results = crawler.batch_crawl(1, 999)
        assert len(results) == 10  # 连续失败达到阈值（10）即中止
        assert all(not ok for ok in results.values())


class TestChampionCrawler:
    def test_get_latest_version_uses_session_timeout_and_numeric_order(self, crawler_env, monkeypatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda s: None)
        crawler = ChampionCrawler(config=crawler_env)
        session = FakeSession(
            responses={DDragon_VERSIONS_URL: FakeResponse(payload=["16.9.9", "16.10.1", "16.10.10", "not-a-version"])}
        )
        crawler.session = session

        assert crawler.get_latest_ddragon_version() == "16.10.10"
        assert session.calls == [(DDragon_VERSIONS_URL, {"params": None, "timeout": crawler.timeout})]

    def test_get_latest_version_retries_transient_request_failure(self, crawler_env, monkeypatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda s: None)
        crawler = ChampionCrawler(config=crawler_env)
        session = FakeSession()
        responses = iter(
            [
                FakeResponse(error=requests.Timeout("slow")),
                FakeResponse(payload=["16.10.1"]),
            ]
        )

        def get(url: str, **kwargs):
            session.calls.append((url, kwargs))
            return next(responses)

        monkeypatch.setattr(session, "get", get)
        crawler.session = session

        assert crawler.get_latest_ddragon_version() == "16.10.1"
        assert len(session.calls) == 2
        assert all(call[1]["timeout"] == crawler.timeout for call in session.calls)

    def test_get_latest_version_rejects_invalid_payload(self, crawler_env, monkeypatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda s: None)
        crawler = ChampionCrawler(config=crawler_env)
        crawler.session = FakeSession(responses={DDragon_VERSIONS_URL: FakeResponse(payload={"version": "16.10.1"})})

        with pytest.raises(ValueError, match="版本接口返回格式错误"):
            crawler.get_latest_ddragon_version()

    def test_crawl_returns_false_when_version_request_fails(self, crawler_env, monkeypatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda s: None)
        crawler = ChampionCrawler(config=crawler_env)
        crawler.session = FakeSession(default=FakeResponse(error=requests.Timeout("slow")))

        assert crawler.crawl() is False

    def test_crawl_fetches_latest_version(self, crawler_env, monkeypatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda s: None)
        crawler = ChampionCrawler(config=crawler_env)
        crawler.fetch_json = lambda url, params=None: {"data": {}}  # type: ignore[method-assign]
        crawler.get_latest_ddragon_version = lambda: "16.9.9"  # type: ignore[method-assign]
        assert crawler.crawl() is True
        saved = json.loads((crawler_env.data_dir / "ddragon" / "champions" / "16.9.9.json").read_text(encoding="utf-8"))
        assert saved == {"data": {}}
