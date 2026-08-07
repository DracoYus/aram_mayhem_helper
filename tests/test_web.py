"""web 模块构建器行为锁定测试（记录形状/打分/列表）。"""

import json

import pytest

import aram_mayhem_helper.web as web_mod
from aram_mayhem_helper.utils.aramkit import AramkitResources
from aram_mayhem_helper.utils.data import ChampionAugmentData, Data


@pytest.fixture
def patch_web_globals(monkeypatch, patch_config_data_path, fixture_trans_table):
    """用 fixture 数据替换 web 模块的全局依赖。"""

    data_dir = patch_config_data_path
    monkeypatch.setattr(
        web_mod,
        "_champion_i18n",
        json.loads((data_dir / "champions-names-i18n.json").read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        web_mod,
        "_augment_descriptions",
        json.loads((data_dir / "aram-mayhem-augments.zh_cn.json").read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(web_mod, "data", Data())
    monkeypatch.setattr(web_mod, "get_default_source", lambda: "opgg")

    resources = AramkitResources()

    def fake_info(source: str, augment_id: str) -> dict | None:
        info = fixture_trans_table.get(str(augment_id))
        if info is None and source == "aramkit":
            return resources.get_augment_info(str(augment_id))
        return info

    monkeypatch.setattr(web_mod, "get_augment_info_for_source", fake_info)
    monkeypatch.setattr(
        web_mod,
        "get_champion_augment_data",
        lambda cid, source=None: ChampionAugmentData(cid, source or "opgg"),
    )
    monkeypatch.setattr(
        web_mod,
        "get_champion_augment_data_dict",
        lambda source=None: {
            "103": ChampionAugmentData("103", source or "opgg"),
            "22": ChampionAugmentData("22", source or "opgg"),
        },
    )


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
    def test_record_key_set_and_values_opgg(self, patch_web_globals) -> None:
        rows = web_mod._build_champion_augments("103", "opgg")
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

    def test_aramkit_display_scale_x100(self, patch_web_globals) -> None:
        rows = web_mod._build_champion_augments("103", "aramkit")
        assert len(rows) == 7
        by_id = {r["augment_id"]: r for r in rows}
        # 0.55 × 100 的 IEEE 浮点产物（特征锁定）
        assert by_id["1001"]["performance_display"] == 55.00000000000001
        assert by_id["1005"]["performance_display"] == 57.99999999999999
        assert by_id["1001"]["performance"] == 0.55
        # 7777 经 aramkit 资源回退
        assert by_id["7777"]["augment_name"] == "测试回退符文"
        assert by_id["7777"]["level"] == "1"

    def test_popular_zero_entries_filtered(self, patch_web_globals) -> None:
        assert web_mod._build_champion_augments("22", "opgg") == []

    def test_unknown_champion_returns_empty(self, patch_web_globals) -> None:
        assert web_mod._build_champion_augments("999", "opgg") == []


class TestBuildChampionList:
    def test_list_shape_and_counts(self, patch_web_globals) -> None:
        lst = web_mod._build_champion_list("opgg")
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
        ]


class TestAugmentDescription:
    def test_strips_pseudo_html_tags(self, patch_web_globals) -> None:
        assert web_mod._augment_description("1001") == "造成适应之力。"

    def test_missing_description_returns_empty(self, patch_web_globals) -> None:
        assert web_mod._augment_description("9999") == ""

    def test_falls_back_to_tooltip(self, patch_web_globals, patch_config_data_path) -> None:
        (patch_config_data_path / "aram-mayhem-augments.zh_cn.json").write_text(
            json.dumps({"1002": {"tooltip": "仅有<attention>提示</attention>。"}}), encoding="utf-8"
        )
        web_mod._augment_descriptions = json.loads(
            (patch_config_data_path / "aram-mayhem-augments.zh_cn.json").read_text(encoding="utf-8")
        )
        assert web_mod._augment_description("1002") == "仅有提示。"
