import logging

import requests
import urllib3

# 禁用 SSL 警告（游戏客户端用自签名证书）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

BASE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"


def _fetch_game_data() -> dict | None:
    """获取当前对局的完整游戏数据。

    :return: allgamedata JSON 字典，失败时返回 None
    """
    try:
        resp = requests.get(BASE_URL, verify=False, timeout=2)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        logger.error('无法连接到游戏客户端，请确保：\n1. 已进入对局\n2. 已开启"允许第三方应用访问游戏数据"')
        return None
    except Exception as e:
        logger.error(f"获取数据失败: {str(e)}")
        return None


def get_current_champion_name() -> str | None:
    """获取正在运行的对局中自己的英雄名称。

    :return: champion_name 或 None
    """
    all_data = _fetch_game_data()
    if not all_data:
        return None

    active_player = all_data.get("activePlayer") or {}
    riot_id = active_player.get("riotId")
    if not riot_id:
        logger.error("未获取到riotId")
        return None

    all_players = all_data.get("allPlayers") or []
    for player in all_players:
        if player.get("riotId") == riot_id:
            raw_champion_name = player.get("rawChampionName")
            champion_name = raw_champion_name and raw_champion_name.split("_")[-1]
            return champion_name

    logger.error("未在玩家列表中找到自己")
    return None


def get_teammate_champions() -> list[dict] | None:
    """获取所有队友的英雄信息。

    队友定义：同队（ORDER / CHAOS）且不是自己的玩家。

    :return: [{"riotId": ..., "championName": ..., "team": ...}, ...] 或 None
    """
    all_data = _fetch_game_data()
    if not all_data:
        return None

    active_player = all_data.get("activePlayer") or {}
    my_riot_id = active_player.get("riotId")
    if not my_riot_id:
        logger.error("未获取到riotId")
        return None

    all_players = all_data.get("allPlayers") or []
    my_team = None

    for player in all_players:
        if player.get("riotId") == my_riot_id:
            my_team = player.get("team")
            break

    if my_team is None:
        logger.error("无法确定自己的队伍")
        return None

    teammates = []
    for player in all_players:
        if player.get("team") == my_team and player.get("riotId") != my_riot_id:
            raw_champion_name = player.get("rawChampionName")
            champion_name = raw_champion_name and raw_champion_name.split("_")[-1]
            teammates.append(
                {
                    "riotId": player.get("riotId"),
                    "championName": champion_name,
                    "team": my_team,
                }
            )

    return teammates


# ================= 调用示例 =================
if __name__ == "__main__":
    champ_name = get_current_champion_name()
    print(f"当前英雄名称: {champ_name}")
