"""数据源更新检查测试（stub session 与 fixture 数据，不发起真实网络请求）。"""

import json
from typing import Any

import pytest
import requests
from test_crawlers import FakeResponse, FakeSession

import aram_mayhem_helper.crawlers.aramkit.aramkit_crawler as aramkit_mod
import aram_mayhem_helper.gui as gui
from aram_mayhem_helper.crawlers.aramkit.aramkit_crawler import AramkitCrawler
from aram_mayhem_helper.crawlers.ddragon.champion_crawler import ChampionCrawler, DDragon_VERSIONS_URL
from aram_mayhem_helper.utils.update_check import UpdateStatus


@pytest.fixture
def crawler_env(monkeypatch: pytest.MonkeyPatch, app_config, game_data):
    """爬虫测试环境：fixture AppConfig + get_game_data 注入（与 test_crawlers 相同）。"""
    monkeypatch.setattr(aramkit_mod, "get_game_data", lambda: game_data)
    return app_config


def _write_version_state(data_dir: Any, data_version: str, resources_version: str) -> None:
    """写入合成的 aramkit 版本状态文件。"""
    version_file = data_dir / "aramkit" / "version.json"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(
        json.dumps({"data_version": data_version, "resources_version": resources_version}),
        encoding="utf-8",
    )


class TestAramkitCheckUpdate:
    DATA_VERSION = "16.15-20260801-aaaaaaaaaaaa"
    RESOURCES_VERSION = "16.15-abc123456789"

    def _html(self) -> str:
        return (
            '<script src="/assets/data/16.14-20260701-111111111111.js"></script>'
            f'<script src="/assets/data/{self.DATA_VERSION}.js"></script>'
            f'<link href="/assets/resources/{self.RESOURCES_VERSION}.css">'
        )

    def _make(self, crawler_env, monkeypatch) -> AramkitCrawler:
        crawler = AramkitCrawler(config=crawler_env)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: self._html())
        return crawler

    def test_update_available(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        _write_version_state(crawler_env.data_dir, "16.14-20260701-111111111111", self.RESOURCES_VERSION)
        status = crawler.check_update()
        assert status.state == "update_available"
        assert status.local_version == "16.14-20260701-111111111111"
        assert status.remote_version == self.DATA_VERSION
        assert "16.14" in status.message and "16.15" in status.message

    def test_up_to_date(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        _write_version_state(crawler_env.data_dir, self.DATA_VERSION, self.RESOURCES_VERSION)
        assert crawler.check_update().state == "up_to_date"

    def test_no_local_data_when_version_file_missing(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        status = crawler.check_update()
        assert status.state == "no_local_data"
        assert status.remote_version == self.DATA_VERSION
        assert status.local_version is None

    def test_unknown_when_homepage_unreachable(self, crawler_env, monkeypatch) -> None:
        crawler = AramkitCrawler(config=crawler_env)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: None)
        _write_version_state(crawler_env.data_dir, self.DATA_VERSION, self.RESOURCES_VERSION)
        status = crawler.check_update()
        assert status.state == "unknown"
        assert status.error is not None

    def test_unknown_when_homepage_has_no_versions(self, crawler_env, monkeypatch) -> None:
        crawler = AramkitCrawler(config=crawler_env)
        monkeypatch.setattr(crawler, "fetch_text", lambda url: "<html>nothing here</html>")
        assert crawler.check_update().state == "unknown"

    def test_check_does_not_write_version_state(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        _write_version_state(crawler_env.data_dir, "16.14-20260701-111111111111", self.RESOURCES_VERSION)
        crawler.check_update()
        state = json.loads((crawler_env.data_dir / "aramkit" / "version.json").read_text(encoding="utf-8"))
        assert state["data_version"] == "16.14-20260701-111111111111"  # 未被检查动作改写

    def test_discover_versions_still_persists_after_refactor(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch)
        crawler.discover_versions()
        state = json.loads((crawler_env.data_dir / "aramkit" / "version.json").read_text(encoding="utf-8"))
        assert state["data_version"] == self.DATA_VERSION
        assert state["resources_version"] == self.RESOURCES_VERSION


class TestDdragonCheckUpdate:
    def _make(self, crawler_env, monkeypatch, payload: Any) -> ChampionCrawler:
        monkeypatch.setattr("time.sleep", lambda s: None)
        crawler = ChampionCrawler(config=crawler_env)
        crawler.session = FakeSession(responses={DDragon_VERSIONS_URL: FakeResponse(payload=payload)})
        return crawler

    def test_update_available(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch, ["16.0.1", "16.1.0"])
        status = crawler.check_update()
        assert status.state == "update_available"
        assert status.local_version == "16.0.1"
        assert status.remote_version == "16.1.0"

    def test_up_to_date(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch, ["16.0.1"])
        assert crawler.check_update().state == "up_to_date"

    def test_up_to_date_when_remote_older_than_local(self, crawler_env, monkeypatch) -> None:
        # 本地比远端新（例如远端接口回退）不应误报更新
        crawler = self._make(crawler_env, monkeypatch, ["15.24.1"])
        assert crawler.check_update().state == "up_to_date"

    def test_no_local_data(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch, ["16.0.1"])
        (crawler_env.data_dir / "ddragon" / "champions").mkdir(parents=True, exist_ok=True)
        for stale in crawler.save_directory.glob("*.json"):
            stale.unlink()
        status = crawler.check_update()
        assert status.state == "no_local_data"
        assert status.remote_version == "16.0.1"

    def test_unknown_when_request_fails(self, crawler_env, monkeypatch) -> None:
        monkeypatch.setattr("time.sleep", lambda s: None)
        crawler = ChampionCrawler(config=crawler_env)
        crawler.session = FakeSession(default=FakeResponse(error=requests.ConnectionError("down")))
        status = crawler.check_update()
        assert status.state == "unknown"
        assert status.error is not None

    def test_check_does_not_write_files(self, crawler_env, monkeypatch) -> None:
        crawler = self._make(crawler_env, monkeypatch, ["16.0.1"])
        before = sorted(p.name for p in crawler.save_directory.iterdir())
        crawler.check_update()
        after = sorted(p.name for p in crawler.save_directory.iterdir())
        assert before == after


class TestUpdateStatusMessage:
    def test_message_variants(self) -> None:
        assert (
            "16.0.1 → 16.1.0"
            in UpdateStatus(
                source="ddragon", state="update_available", local_version="16.0.1", remote_version="16.1.0"
            ).message
        )
        assert "已是最新" in UpdateStatus(source="ddragon", state="up_to_date", local_version="16.0.1").message
        assert "暂无" in UpdateStatus(source="ddragon", state="no_local_data", remote_version="16.0.1").message
        assert "检查失败" in UpdateStatus(source="ddragon", state="unknown", error="超时").message

    def test_unknown_source_label_falls_back_to_source_name(self) -> None:
        message = UpdateStatus(source="opgg", state="up_to_date", local_version="1").message
        assert "opgg" in message


class TestGuiUpdateCheckWiring:
    def test_start_update_checks_runs_in_background_task(self, monkeypatch) -> None:
        started: list[str] = []
        monkeypatch.setattr(gui, "_check_all_updates_worker", lambda source: started.append(source))
        captured: dict[str, Any] = {}

        def fake_run_in_background(target, description, log_area, buttons, on_done=None, *, task_name="default"):
            captured["task_name"] = task_name
            target()

        monkeypatch.setattr(gui, "_run_in_background", fake_run_in_background)
        gui.start_update_checks(log_area=None, source="aramkit")  # type: ignore[arg-type]
        assert started == ["aramkit"]
        assert captured["task_name"] == "check"

    def test_source_check_skips_opgg(self, monkeypatch) -> None:
        checked: list[str] = []
        monkeypatch.setattr(gui, "_check_aramkit_update", lambda: checked.append("aramkit"))
        gui._UPDATE_CHECK_CACHE.clear()
        gui._check_source_update_worker("opgg")
        assert checked == []

    def test_source_check_uses_cache_on_second_call(self, monkeypatch) -> None:
        checked: list[str] = []
        status = UpdateStatus(source="aramkit", state="up_to_date", local_version="16.15-20260801-aaaaaaaaaaaa")
        monkeypatch.setattr(gui, "_check_aramkit_update", lambda: checked.append("aramkit") or status)
        gui._UPDATE_CHECK_CACHE.clear()
        gui._check_source_update_worker("aramkit")
        gui._check_source_update_worker("aramkit")
        assert checked == ["aramkit"]  # 第二次走缓存

    def test_start_source_update_check_runs_in_background_task(self, monkeypatch) -> None:
        started: list[str] = []
        monkeypatch.setattr(gui, "_check_source_update_worker", lambda source: started.append(source))
        captured: dict[str, Any] = {}

        def fake_run_in_background(target, description, log_area, buttons, on_done=None, *, task_name="default"):
            captured["task_name"] = task_name
            target()

        monkeypatch.setattr(gui, "_run_in_background", fake_run_in_background)
        gui.start_source_update_check(log_area=None, source="aramkit")  # type: ignore[arg-type]
        assert started == ["aramkit"]
        assert captured["task_name"] == "check"
