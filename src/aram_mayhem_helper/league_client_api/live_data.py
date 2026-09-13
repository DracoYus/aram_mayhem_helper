import logging

import requests
import urllib3

logger = logging.getLogger(__name__)

# Live Client Data API 地址（固定端口 2999）
_LIVE_CLIENT_DATA_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
# 本地回环接口，超时从短：游戏未进对局时快速失败而不是挂住调用方
_REQUEST_TIMEOUT_SECONDS = 2

_ssl_warnings_disabled = False


def _disable_ssl_warnings_once() -> None:
    """禁用 SSL 警告（游戏客户端用自签名证书），进程内只执行一次。"""
    global _ssl_warnings_disabled
    if not _ssl_warnings_disabled:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        _ssl_warnings_disabled = True


def get_current_champion_name() -> str | None:
    """
    获取正在运行的对局中自己的英雄 ID 和名称
    :return: champion_name 或 None
    """
    _disable_ssl_warnings_once()

    try:
        # 1. 获取当前活跃玩家数据
        active_player_resp = requests.get(
            _LIVE_CLIENT_DATA_URL,
            verify=False,  # 忽略证书验证
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        active_player_resp.raise_for_status()  # 检查请求是否成功
        all_data = active_player_resp.json()

        # 2. 提取用户riotId（召唤师名称）
        active_player = all_data.get("activePlayer") or {}
        riot_id = active_player.get("riotId")
        if not riot_id:
            logger.error("未获取到riotId")
            return None

        raw_champion_name = None
        # 3.找到自己的英雄名称（通过 summonerName 匹配）
        all_players = all_data.get("allPlayers") or []
        for player in all_players:
            if player.get("riotId") == riot_id:
                raw_champion_name = player.get("rawChampionName")
                break

        champion_name = raw_champion_name and raw_champion_name.split("_")[-1]
        return champion_name

    except requests.exceptions.ConnectionError:
        logger.error('无法连接到游戏客户端，请确保：\n1. 已进入对局\n2. 已开启"允许第三方应用访问游戏数据"')
        return None
    except Exception as e:
        logger.error(f"获取数据失败: {str(e)}")
        return None


# ================= 调用示例 =================
if __name__ == "__main__":
    champ_name = get_current_champion_name()
    print(f"当前英雄名称: {champ_name}")
