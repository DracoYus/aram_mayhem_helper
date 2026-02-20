import json
import logging
from pathlib import Path
from typing import Dict

import requests

from aram_mayhem_helper.utils.config import config


class Data:
    def __init__(self):
        self.game_version: str | None = None
        self.champion_data: Dict[str, dict] = {}
        self.logger = logging.getLogger(__name__)

    def get_all_champion_data(self) -> Dict[str, dict]:
        """获取所有英雄的完整数据"""
        if not self.champion_data:
            champion_data_path = config.data_path / Path(config.get("crawler", "ddragon", "champion", "save_directory"))
            files = [f for f in champion_data_path.iterdir() if f.is_file()]
            if not files:
                self.logger.error(f"没有找到任何英雄数据文件在: {champion_data_path}")
                return {}
            latest_file = max(files, key=lambda f: f.name)
            try:
                with open(latest_file, "r", encoding="utf-8") as f:
                    self.champion_data = json.load(f)["data"]

            except Exception as e:
                self.logger.error(f"读取英雄ID时发生错误: {str(e)}")
        return self.champion_data

    def get_latest_ddragon_version(self) -> str:
        url = "https://ddragon.leagueoflegends.com/api/versions.json"
        response = requests.get(url)
        versions = response.json()
        return versions[0]  # 第一个元素是最新版本

    def get_game_version(self) -> str | None:
        """获取游戏版本"""
        if not self.game_version:
            try:
                url = "https://ddragon.leagueoflegends.com/api/versions.json"
                response = requests.get(url)
                versions = response.json()
                self.game_version = versions[0]  # 第一个元素是最新版本
            except Exception as e:
                self.logger.error(f"获取游戏版本时发生错误: {str(e)}")
                self.game_version = None
        return self.game_version

    def get_champion_id_by_name(self, champion_name: str) -> str | None:
        """根据英雄名称获取英雄 ID"""
        champion_data = self.get_all_champion_data()
        for champ_id, champ_info in champion_data.items():
            if champ_info["id"].lower() == champion_name.lower():
                return champ_info["key"]
        self.logger.warning(f"未找到英雄名称 '{champion_name}' 对应的 ID")
        return None


class ChampionAugmentData:
    def __init__(self, champion_id: str):
        self.champion_id = champion_id
        self.champion_augment_data = None
        self.logger = logging.getLogger(__name__)

    def get_champion_augment_data(self) -> list[dict]:
        """获取英雄符文数据"""
        if not self.champion_augment_data:
            champion_data_path = (
                config.data_path
                / Path(config.get("crawler", "opgg", "aram_augment", "save_directory"))
                / f"{self.champion_id}.json"
            )
            with open(champion_data_path, "r", encoding="utf-8") as f:
                # 2. 读取并解析 JSON 数据
                self.champion_augment_data = json.load(f)
        return self.champion_augment_data["data"]


class AugmentTool:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.id_name_dict = {}
        self.name_id_dict = {}
        trans_file = config.data_path / "augment_trans.json"
        if trans_file.exists():
            with open(trans_file, "r", encoding="utf-8") as f:
                self.id_name_dict = json.load(f)
        else:
            self.logger.warning(f"未找到翻译文件: {trans_file}")
        for aug_id, info in self.id_name_dict.items():
            self.name_id_dict[info["name"]] = {"id": aug_id, "level": info["level"]}

    def get_augment_id(self, augment_name: str) -> str | None:
        """根据符文名称获取符文ID"""
        augment_info = self.name_id_dict.get(augment_name, None)
        if augment_info:
            return augment_info["id"]

    def get_augment_info(self, augment_id: str) -> dict | None:
        """根据符文名称获取符文ID"""
        return self.id_name_dict.get(augment_id, None)


data = Data()
champion_augment_data_dict = {}
for champion, champion_info in data.get_all_champion_data().items():
    champion_augment_data_dict[champion_info["key"]] = ChampionAugmentData(champion_info["key"])
augment_tool = AugmentTool()

if __name__ == "__main__":
    data = Data()
    print(data.get_game_version())
    print(data.get_all_champion_data())
    print(data.get_champion_id_by_name("Smolder"))
    augment_tool = AugmentTool()
    print(augment_tool.get_augment_id("老练狙神"))
