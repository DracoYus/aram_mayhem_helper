"""league_client_api.live_data 行为锁定测试（mock requests.get）。"""

import pytest
import requests

import aram_mayhem_helper.league_client_api.live_data as live_data


class FakeResponse:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> dict:
        return self._payload


def _mock_get(monkeypatch: pytest.MonkeyPatch, response: FakeResponse) -> dict:
    captured: dict = {}

    def fake_get(url: str, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    return captured


def _game_payload(riot_id: str = "召唤师#1234") -> dict:
    return {
        "activePlayer": {"riotId": riot_id},
        "allPlayers": [
            {"riotId": "队友#9999", "rawChampionName": "game_character_Annie"},
            {"riotId": riot_id, "rawChampionName": "game_character_Ahri"},
        ],
    }


class TestGetCurrentChampionName:
    def test_returns_own_champion_name(self, monkeypatch) -> None:
        captured = _mock_get(monkeypatch, FakeResponse(_game_payload()))
        assert live_data.get_current_champion_name() == "Ahri"
        assert captured["url"] == "https://127.0.0.1:2999/liveclientdata/allgamedata"
        assert captured["kwargs"] == {"verify": False, "timeout": 2}

    def test_missing_riot_id_returns_none(self, monkeypatch) -> None:
        _mock_get(monkeypatch, FakeResponse({"activePlayer": {}, "allPlayers": []}))
        assert live_data.get_current_champion_name() is None

    def test_no_matching_player_returns_none(self, monkeypatch) -> None:
        payload = _game_payload(riot_id="召唤师#1234")
        payload["allPlayers"][1]["rawChampionName"] = None  # 匹配到但无 rawChampionName
        _mock_get(monkeypatch, FakeResponse(payload))
        assert live_data.get_current_champion_name() is None

    def test_connection_error_returns_none(self, monkeypatch) -> None:
        _mock_get(monkeypatch, FakeResponse(error=requests.exceptions.ConnectionError("refused")))
        assert live_data.get_current_champion_name() is None

    def test_generic_error_returns_none(self, monkeypatch) -> None:
        _mock_get(monkeypatch, FakeResponse(error=requests.exceptions.Timeout("slow")))
        assert live_data.get_current_champion_name() is None
