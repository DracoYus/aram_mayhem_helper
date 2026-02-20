import logging

from aram_mayhem_helper.utils.data import ChampionAugmentData, augment_tool


class Suggest:
    def __init__(self, champion_augment_data: ChampionAugmentData):
        self.logger = logging.getLogger(__name__)
        self.champion_augment_data = champion_augment_data.get_champion_augment_data()
        self.augment_group = {}
        for item in self.champion_augment_data:
            # 根据符文级别对符文进行分组
            augment_info = augment_tool.get_augment_info(str(item["id"]))
            level = augment_info["level"]
            item["level"] = level
            item["name"] = augment_info["name"]
            if level not in self.augment_group:
                self.augment_group[level] = []
            self.augment_group[level].append(item)
        for group_level, group_data in self.augment_group.items():
            #  对每个组进行排序，统计名次
            sorted_group_data = sorted(group_data, key=lambda x: x["performance"], reverse=True)
            for idx, item in enumerate(sorted_group_data):
                item["rank"] = idx + 1

    def get_augment_info_by_id(self, augment_id: str) -> dict:
        """
        使用符文id查询对应符文信息

        Args:
            augment_id (str): 符文id

        Returns:
            dict: 符文信息
        """
        for item in self.champion_augment_data:
            if str(item["id"]) == augment_id:
                return item

    def suggest(self, augments: list[str]) -> list:
        """
        根据输入符文信息，给出操作推荐

        Args:
            augments (list[str]): 输入符文信息

        Returns:
            list: 操作推荐
        """
        augment_ids = [augment_tool.get_augment_id(augment) for augment in augments]
        augment_info = [self.get_augment_info_by_id(augment_id) for augment_id in augment_ids]
        for item in augment_info:
            self.logger.info(item)


if __name__ == "__main__":
    champion_augment_data = ChampionAugmentData(99)
    suggest = Suggest(champion_augment_data)
    suggest.suggest(["老练狙神", "红包", "吞噬灵魂"])
