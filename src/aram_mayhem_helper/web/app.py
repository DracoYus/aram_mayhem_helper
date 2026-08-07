"""ARAM Mayhem Helper 网页应用 — 浏览缓存的所有英雄符文数据。"""

import logging

from flask import Flask, Response, jsonify, render_template, request

from aram_mayhem_helper.utils.data import GameData, get_game_data
from aram_mayhem_helper.web.service import build_champion_augments, build_champion_list

logger = logging.getLogger(__name__)


def create_app(game_data: GameData | None = None) -> Flask:
    """创建 Flask 应用（工厂模式，便于测试注入 fixture 数据）。

    Args:
        game_data: 数据仓储，None 时取全局单例
    """
    gd = game_data or get_game_data()
    app = Flask(__name__)

    @app.route("/")
    def index() -> str:
        """Serve the main page."""
        return render_template("index.html", default_source=gd.default_source())

    @app.route("/api/champions")
    def api_champions() -> Response | tuple[Response, int]:
        """Return a summary list of all champions with cached augment data."""
        source = request.args.get("source", gd.default_source())
        try:
            return jsonify(build_champion_list(gd, source))
        except Exception as e:
            logger.error(f"构建英雄列表失败: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/champions/<champion_id>/augments")
    def api_champion_augments(champion_id: str) -> Response | tuple[Response, int]:
        """Return normalized augment data for a specific champion."""
        source = request.args.get("source", gd.default_source())
        try:
            return jsonify(build_champion_augments(gd, champion_id, source))
        except Exception as e:
            logger.error(f"构建英雄 {champion_id} 符文数据失败: {e}")
            return jsonify({"error": str(e)}), 500

    return app
