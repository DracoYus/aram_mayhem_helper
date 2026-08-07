"""web 服务层与应用工厂测试（记录形状/打分/列表/路由）。"""

import json

import pytest

from aram_mayhem_helper.web.app import create_app
from aram_mayhem_helper.web.service import augment_description, build_champion_augments, build_champion_list


@pytest.fixture
def patch_i18n_files(monkeypatch, fixture_data_dir):
    """把 service 的 i18n/描述加载替换为 fixture 数据。"""
    import aram_mayhem_helper.web.service as service

    i18n = json.loads((fixture_data_dir / "champions-names-i18n.json").read_text(encoding="utf-8"))
    desc = json.loads((fixture_data_dir / "aram-mayhem-augments.zh_cn.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(service, "_load_champion_i18n", lambda: i18n)
    monkeypatch.setattr(service, "_load_augment_descriptions", lambda: desc)


RECORD_KEYS = {
    "champion_id",
    "champion_name",
    "champion_name_cn",
    "champion_alias",
    "augment_id",
    "augment_name",
    "description",
    "level",
    "performance",
    "popular",
    "performance_display",
    "popular_display",
    "performance_unit",
    "popular_unit",
    "weighted_sum",
    "performance_norm",
    "popular_norm",
}


class TestBuildChampionAugments:
    def test_record_key_set_and_values_opgg(self, game_data, patch_i18n_files) -> None:
        rows = build_champion_augments(game_data, "103", "opgg")
        assert len(rows) == 6
        assert all(set(r.keys()) == RECORD_KEYS for r in rows)
        first = rows[0]  # 文件顺序保持（不按分数排序）
        assert first["augment_id"] == "1001"
        assert first["augment_name"] == "泰坦的坚决"
        assert first["champion_name_cn"] == "九尾妖狐"
        assert first["description"] == "造成适应之力。"
        assert first["level"] == "2"
        assert first["weighted_sum"] == pytest.approx(0.5)
        assert first["performance_norm"] == pytest.approx(0.8616)
        assert first["performance_display"] == pytest.approx(80.0)
        assert first["popular_display"] == pytest.approx(10.0)

    def test_aramkit_display_scale_x100(self, game_data, patch_i18n_files) -> None:
        rows = build_champion_augments(game_data, "103", "aramkit")
        assert len(rows) == 7
        by_id = {r["augment_id"]: r for r in rows}
        # 0.55 × 100 的 IEEE 浮点产物（特征锁定）
        assert by_id["1001"]["performance_display"] == 55.00000000000001
        assert by_id["1005"]["performance_display"] == 57.99999999999999
        assert by_id["1001"]["performance"] == 0.55
        # 7777 经 aramkit 资源回退
        assert by_id["7777"]["augment_name"] == "测试回退符文"
        assert by_id["7777"]["level"] == "1"

    def test_popular_zero_entries_filtered(self, game_data, patch_i18n_files) -> None:
        assert build_champion_augments(game_data, "22", "opgg") == []

    def test_unknown_champion_returns_empty(self, game_data, patch_i18n_files) -> None:
        assert build_champion_augments(game_data, "999", "opgg") == []


class TestBuildChampionList:
    def test_list_shape_and_counts(self, game_data, patch_i18n_files) -> None:
        lst = build_champion_list(game_data, "opgg")
        assert lst == [
            {
                "champion_id": "22",
                "champion_name": "Ashe",
                "champion_name_cn": "寒冰射手",
                "champion_alias": "Ashe",
                "augment_count": 0,
            },
            {
                "champion_id": "103",
                "champion_name": "Ahri",
                "champion_name_cn": "九尾妖狐",
                "champion_alias": "Ahri",
                "augment_count": 7,
            },
            {
                "champion_id": "266",
                "champion_name": "Aatrox",
                "champion_name_cn": "",
                "champion_alias": "",
                "augment_count": 0,
            },
        ]


class TestAugmentDescription:
    def test_strips_pseudo_html_tags(self, game_data, patch_i18n_files) -> None:
        assert augment_description("1001") == "造成适应之力。"

    def test_missing_description_returns_empty(self, game_data, patch_i18n_files) -> None:
        assert augment_description("9999") == ""


class TestCreateApp:
    def test_index_renders_with_default_source(self, game_data, patch_i18n_files) -> None:
        client = create_app(game_data).test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "ARAM 符文数据浏览" in html

    def test_api_champions_shape(self, game_data, patch_i18n_files) -> None:
        client = create_app(game_data).test_client()
        resp = client.get("/api/champions?source=opgg")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 3
        assert data[1]["champion_id"] == "103"
        assert data[1]["augment_count"] == 7

    def test_api_champion_augments_record_keys(self, game_data, patch_i18n_files) -> None:
        client = create_app(game_data).test_client()
        resp = client.get("/api/champions/103/augments?source=opgg")
        assert resp.status_code == 200
        rows = resp.get_json()
        assert len(rows) == 6
        assert set(rows[0].keys()) == RECORD_KEYS
        assert rows[0]["weighted_sum"] == pytest.approx(0.5)

    def test_api_aramkit_source_switch(self, game_data, patch_i18n_files) -> None:
        client = create_app(game_data).test_client()
        resp = client.get("/api/champions/103/augments?source=aramkit")
        assert resp.status_code == 200
        rows = resp.get_json()
        assert rows[0]["performance"] == 0.55

    def test_api_unknown_champion_returns_empty_list(self, game_data, patch_i18n_files) -> None:
        client = create_app(game_data).test_client()
        resp = client.get("/api/champions/999/augments?source=opgg")
        assert resp.status_code == 200
        assert resp.get_json() == []
