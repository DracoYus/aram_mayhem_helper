import logging

from aram_mayhem_helper.algorithm.suggest import Suggest
from aram_mayhem_helper.utils.config import config

LEVEL_LABELS = {"2": "棱彩", "1": "黄金", "0": "白银"}


class TeamAnalysis:
    """逐队友逐等级符文分析：每个队友的每个符文等级给出优先选择和陷阱。

    用法::

        champions = {"阿狸": Suggest实例, "艾尼维亚": Suggest实例, ...}
        analysis = TeamAnalysis(champions)
        text = analysis.format_output()
    """

    def __init__(self, champions: dict[str, Suggest]) -> None:
        """
        :param champions: {champion_zh_name: Suggest}
        """
        self.champions = champions
        self.logger = logging.getLogger(__name__)
        self.priority_count = config.get("team_analysis", "priority_count")
        self.trap_count = config.get("team_analysis", "trap_count")
        self.trap_pop_threshold = config.get("team_analysis", "trap_pop_threshold")
        self.trap_perf_threshold = config.get("team_analysis", "trap_perf_threshold")
        self._results: dict | None = None

    def analyze(self) -> dict:
        """执行完整分析，返回结构化结果。

        :return: {champion_name: {level: {"priorities": [...], "traps": [...]}}}
        """
        if self._results is not None:
            return self._results

        results: dict[str, dict] = {}

        for champ_name, suggest in self.champions.items():
            champ_results: dict[str, dict] = {}
            for level in ["2", "1", "0"]:
                level_result = self._analyze_champion_level(suggest, level)
                if level_result.get("priorities") or level_result.get("traps"):
                    champ_results[level] = level_result
            if champ_results:
                results[champ_name] = champ_results

        self._results = results
        return results

    def _analyze_champion_level(self, suggest: Suggest, level: str) -> dict:
        """分析单个英雄单个等级的符文。

        :return: {"priorities": [{...}], "traps": [{...}]}
        """
        group = suggest.augment_group.get(level)
        if not group:
            return {"priorities": [], "traps": []}

        augments = group["augments"]
        if not augments:
            return {"priorities": [], "traps": []}

        # 优先选择：已按 weighted_sum 降序排列，直接取前 priority_count 个
        priorities = []
        for item in augments[: self.priority_count]:
            priorities.append(
                {
                    "id": str(item["id"]),
                    "name": item["name"],
                    "weighted_sum": item.get("weighted_sum", 0),
                    "rank": item.get("rank", 0),
                    "group_size": item.get("group_size", 0),
                }
            )

        # 陷阱：流行度高但表现低的符文
        trap_candidates = []
        for item in augments:
            pop_norm = item.get("popular_norm", 0)
            perf_norm = item.get("performance_norm", 0)
            if pop_norm > self.trap_pop_threshold and perf_norm < self.trap_perf_threshold:
                trap_candidates.append(
                    {
                        "id": str(item["id"]),
                        "name": item["name"],
                        "popular_norm": pop_norm,
                        "performance_norm": perf_norm,
                        "gap": pop_norm - perf_norm,
                    }
                )

        trap_candidates.sort(key=lambda x: x["gap"], reverse=True)
        traps = trap_candidates[: self.trap_count]

        return {"priorities": priorities, "traps": traps}

    def format_output(self) -> str:
        """生成聊天友好的多行文本输出。"""
        results = self.analyze()
        if not results:
            return "当前队伍没有可分析的符文数据"

        lines = ["=== 队友符文 ==="]
        for champ_name in self.champions:
            champ_data = results.get(champ_name)
            if not champ_data:
                continue

            lines.append(f"[{champ_name}]")

            for level in ["2", "1", "0"]:
                level_data = champ_data.get(level)
                if not level_data:
                    continue
                label = LEVEL_LABELS.get(level, f"Lv{level}")
                parts = []

                priorities = level_data.get("priorities", [])
                if priorities:
                    names = "|".join(a["name"] for a in priorities)
                    parts.append(f"→{names}")

                traps = level_data.get("traps", [])
                if traps:
                    names = "|".join(a["name"] for a in traps)
                    parts.append(f"✗{names}")

                if parts:
                    lines.append(f"  [{label}] {' '.join(parts)}")

        return "\n".join(lines)

    def get_summary(self) -> dict:
        """返回结构化结果，供日志/测试使用。"""
        return self.analyze()
