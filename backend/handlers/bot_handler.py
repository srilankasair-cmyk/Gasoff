"""Telegram bot webhook handler using Flask Blueprint."""

import json
import logging
import uuid
from typing import Optional

from flask import Blueprint, request, jsonify

from backend.config.settings import settings
from backend.models.schemas import AnalysisResult, TelegramUpdate
from backend.services.deidentifier import deidentify
from backend.services.analyzer import analyze_conversation, AnalysisError

logger = logging.getLogger(__name__)

bp = Blueprint("bot", __name__)

_analysis_store: dict[str, Optional[AnalysisResult]] = {}


def _twa_base_url() -> str:
    """Return the public base URL for TWA links."""
    configured = settings.TELEGRAM_WEBHOOK_URL.strip().rstrip("/")
    if configured and configured != "https://YOUR_PUBLIC_DOMAIN.com":
        return configured
    # Fallback: guess from request
    return request.host_url.rstrip("/")


@bp.route("/webhook", methods=["POST"])
def telegram_webhook():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"ok": False, "error": "Invalid JSON"}), 400

    logger.debug(f"Webhook received: {json.dumps(body, ensure_ascii=False)[:200]}...")

    try:
        update = TelegramUpdate(**body)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Invalid update: {e}"}), 400

    msg = update.message
    if not msg or not msg.text:
        return jsonify({"ok": True, "status": "ignored"})

    # Step 1: De-identify
    clean_result = deidentify(msg.text)
    analysis_id = str(uuid.uuid4())[:8]

    # Step 2: Analyze
    import asyncio
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(analyze_conversation(clean_result.clean_text))
        loop.close()
        _analysis_store[analysis_id] = result
        status = "completed"
    except AnalysisError:
        _analysis_store[analysis_id] = None
        status = "error"

    # Step 3: Build Telegram response
    if status == "completed" and _analysis_store.get(analysis_id):
        result = _analysis_store[analysis_id]
        response_text = (
            f"✅ 信息脱敏已完成，云端分析结束！\n\n"
            f"📊 关系毒性值：{result.toxicity_score}%\n"
            f"⚠️ 检测到 {len(result.toxic_sentences)} 处有毒话术\n\n"
            f"🔍 点击下方按钮查看完整人际关系图谱"
        )
        twa_url = f"{_twa_base_url()}/twa/{analysis_id}"
        reply_markup = {
            "inline_keyboard": [[
                {
                    "text": "🔬 查看深度人际图谱",
                    "web_app": {"url": twa_url}
                }
            ]]
        }
    else:
        response_text = "⚠️ 分析过程出现错误，请稍后重试。"
        reply_markup = None

    resp = {
        "method": "sendMessage",
        "chat_id": msg.chat.id,
        "text": response_text,
    }
    if reply_markup:
        resp["reply_markup"] = reply_markup

    return jsonify(resp)


@bp.route("/api/analysis/<analysis_id>")
def get_analysis(analysis_id: str):
    result = _analysis_store.get(analysis_id)
    if result is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(result.model_dump())
