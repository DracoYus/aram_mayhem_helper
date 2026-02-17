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


data = Data()

if __name__ == "__main__":
    data = Data()
    print(data.get_game_version())
    print(data.get_all_champion_data())
