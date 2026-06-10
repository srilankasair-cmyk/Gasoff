"""Telegram bot webhook handler with subscription gating.

First analysis is free. Subsequent analyses require a Telegram Stars
subscription (50 Stars / 30 days).
"""

import json
import logging
import threading
import time
import uuid
from typing import Optional

import requests
from flask import Blueprint, request, jsonify

from backend.config.settings import settings
from backend.models.schemas import AnalysisResult, TelegramUpdate
from backend.services.deidentifier import deidentify
from backend.services.analyzer import analyze_conversation, AnalysisError
from backend.services.subscription import (
    can_analyze,
    use_analysis,
    remaining_free,
    activate_subscription,
    get_user,
)

logger = logging.getLogger(__name__)
bp = Blueprint("bot", __name__)

_analysis_store: dict[str, Optional[AnalysisResult]] = {}

_lock = threading.Lock()
_buffers: dict[int, dict] = {}

STAR_PRICE = 150


def _twa_base_url() -> str:
    configured = settings.TELEGRAM_WEBHOOK_URL.strip().rstrip("/")
    if configured and configured != "https://YOUR_PUBLIC_DOMAIN.com":
        return configured
    return request.host_url.rstrip("/")


# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------
def _telegram_send(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> bool:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return False
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=15,
        )
        if resp.status_code == 200:
            return True
        logger.error("Telegram fail %s: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.error("Telegram error: %s", e)
        return False


def _send_invoice(chat_id: int) -> bool:
    """Send a Telegram Stars invoice for subscription."""
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendInvoice",
            json={
                "chat_id": chat_id,
                "title": "Tox Detector Premium",
                "description": "🌟 Launch special: 150 Stars (normally 250)! Unlimited analysis for 30 days. Save 40%!",
                "payload": "toxdetector_sub_30d",
                "currency": "XTR",
                "provider_token": "", "prices": [{"amount": STAR_PRICE, "label": "30-Day Subscription"}],
            },
            timeout=15,
        )
        ok = resp.status_code == 200
        if not ok:
            err_text = resp.text[:300]
            logger.error("sendInvoice fail: %s %s", resp.status_code, err_text)
        return ok
    except Exception as e:
        logger.error("sendInvoice error: %s", e)
        return False


def _answer_callback(callback_id: str, text: str = "") -> None:
    """Answer a callback query (immediately stops the loading state)."""
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text, "show_alert": False},
            timeout=10,
        )
    except Exception as e:
        logger.error("answerCallbackQuery error: %s", e)


def _answer_pre_checkout(query_id: str, ok: bool = True) -> None:
    """Answer a pre_checkout_query."""
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerPreCheckoutQuery",
            json={"pre_checkout_query_id": query_id, "ok": ok},
            timeout=10,
        )
    except Exception as e:
        logger.error("answerPreCheckoutQuery error: %s", e)


# ---------------------------------------------------------------------------
# Speaker detection
# ---------------------------------------------------------------------------
def _detect_speaker(msg) -> tuple[str, str]:
    bot_user_id = msg.from_user.id if msg.from_user else 0
    bot_user_name = msg.from_user.first_name if msg.from_user else "You"
    if msg.forward_from:
        name = msg.forward_from.first_name or "Someone"
        if msg.forward_from.id == bot_user_id:
            return ("user", name)
        else:
            return ("other", name)
    elif msg.forward_sender_name:
        return ("other", msg.forward_sender_name)
    else:
        return ("user", bot_user_name)


def _build_conversation(entries: list[dict]) -> str:
    lines = []
    for e in entries:
        label = "You" if e["speaker"] == "user" else "Other"
        lines.append(f"[{label}: {e['name']}] {e['text']}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _fmt_toxicity(result: AnalysisResult) -> str:
    score = int(result.toxicity_score)
    direction = result.toxicity_direction
    explanation = result.toxicity_explanation
    name = result.other_name or "the other person"

    # Score-based tiered descriptions
    if score <= 10:
        tier = "healthy communication"
    elif score <= 25:
        tier = "mild negative patterns"
    elif score <= 50:
        tier = "moderate toxicity"
    elif score <= 75:
        tier = "significant toxicity"
    else:
        tier = "severe toxicity"

    if direction == "self_to_other":
        icon, label = "⬇️", f"-{score}%"
        desc = f"You show {tier} toward {name}"
    elif direction == "mutual":
        icon, label = "🔄", f"{score}%"
        desc = f"Mutual {tier} detected"
    else:
        icon, label = "⬆️", f"+{score}%"
        desc = f"{name} shows {tier} toward you"
    parts = [f"📊 Toxicity Score: {icon} {label} ({desc})"]
    if explanation:
        parts.append(f"💡 {explanation}")
    return "\n".join(parts)


def _fmt_gottman(result: AnalysisResult) -> str:
    u = result.gottman.user
    o = result.gottman.other
    return (
        "📋 Gottman Four Horsemen:\n\n"
        f"▎You: \n"
        f"  Criticism {u.criticism:.0f}% | Contempt {u.contempt:.0f}% | "
        f"Defensiveness {u.defensiveness:.0f}% | Stonewalling {u.stonewalling:.0f}%\n\n"
        f"▎Other Person:\n"
        f"  Criticism {o.criticism:.0f}% | Contempt {o.contempt:.0f}% | "
        f"Defensiveness {o.defensiveness:.0f}% | Stonewalling {o.stonewalling:.0f}%"
    )


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------
def _flush(chat_id: int, user_id: int) -> None:
    with _lock:
        buf = _buffers.pop(chat_id, None)
    if buf is None:
        return
    entries = buf.get("entries", [])
    if not entries:
        return

    conversation = _build_conversation(entries)
    logger.info("FLUSH chat=%s user=%s (%d msgs)", chat_id, user_id, len(entries))

    if not _telegram_send(chat_id, "🔐 De-identifying your conversation..."):
        return
    try:
        clean = deidentify(conversation)
    except Exception:
        logger.exception("Deidentify failed")
        _telegram_send(chat_id, "⚠️ De-identification failed, please try again")
        return

    _telegram_send(chat_id, "✅ De-identification complete. Uploading for AI analysis...")

    aid = str(uuid.uuid4())[:8]
    try:
        result = analyze_conversation(clean.clean_text)
        _analysis_store[aid] = result
        logger.info("Analysis OK toxicity=%s dir=%s", result.toxicity_score, result.toxicity_direction)
    except Exception:
        logger.exception("Analysis failed")
        _telegram_send(chat_id, "⚠️ Analysis failed, please try again")
        return

    # Mark this analysis as used
    use_analysis(user_id)

    resp_parts = [
        "✅ Analysis Complete!\n",
        _fmt_toxicity(result),
        "",
        "🔍 Tap below to view the full relationship dashboard",
    ]
    text = "\n".join(resp_parts)
    twa = f"{_twa_base_url()}/twa/{aid}"
    markup = {"inline_keyboard": [[{"text": "🔬 View Full Analysis", "web_app": {"url": twa}}]]}
    _telegram_send(chat_id, text, markup)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------
@bp.route("/webhook", methods=["POST"])
def telegram_webhook():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"ok": False, "error": "Invalid JSON"}), 400
    try:
        update = TelegramUpdate(**body)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Invalid update: {e}"}), 400

    # ── Handle pre_checkout_query ──
    if update.pre_checkout_query:
        _answer_pre_checkout(update.pre_checkout_query.id, ok=True)
        logger.info("Approved pre_checkout_query %s", update.pre_checkout_query.id)
        return jsonify({"ok": True, "status": "pre_checkout_answered"})

    # ── Handle callback_query ──
    if update.callback_query:
        cq = update.callback_query
        # Always answer callback immediately to stop loading state
        _answer_callback(cq.id, "")
        if cq.data == "subscribe":
            chat_id = cq.message.chat.id if cq.message else 0
            ok = _send_invoice(chat_id)
            if not ok:
                _telegram_send(chat_id, "⚠️ Failed to create invoice. Please try again later.")
        return jsonify({"ok": True, "status": "callback_handled"})

    # ── Handle message ──
    msg = update.message
    if not msg:
        return jsonify({"ok": True, "status": "ignored"})

    chat_id = msg.chat.id
    user_id = msg.from_user.id if msg.from_user else 0

    # ── Handle successful payment ──
    if msg.successful_payment:
        activate_subscription(user_id)
        _telegram_send(
            chat_id,
            "🎉 **Welcome to Tox Detector Premium!**\n\n"
            "✅ Payment received — your Premium subscription is active for 30 days\n"
            "✅ Unlimited relationship analysis\n"
            "✅ Priority processing\n\n"
            "Forward a chat to analyze right now 👇",
        )
        return jsonify({"ok": True, "status": "subscribed"})

    # ── Handle text commands ──
    if msg.text:
        text = msg.text.strip()

        if text == "/start":
            free_left = remaining_free(user_id)
            _telegram_send(chat_id,
                "👋 Welcome to **Tox Detector**!\n\n"
                "📌 **What is this?**\n"
                "Based on psychology research (Gottman Four Horsemen + "
                "Interpersonal Circumplex Model) to analyze unhealthy "
                "communication patterns in your chats.\n\n"
                "🎁 **Free Trial:** You have "
                f"{free_left} free analysis{'es' if free_left != 1 else ''}.\n"
                "After that, subscribe via Telegram Stars.\n\n"
                "📌 **How to use:**\n"
                "1️⃣ Open any chat (private or group)\n"
                "2️⃣ Long-press a message → tap **Select**\n"
                "3️⃣ Select the messages you want analyzed\n"
                "4️⃣ Tap **Forward** → choose **Tox Detector** → Send\n"
                "5️⃣ Wait 2 seconds — the analysis appears automatically\n\n"
                "🔐 All conversations are de-identified before analysis "
                "to protect your privacy.\n\n"
                "Try it now — forward a message! 👇")
            return jsonify({"ok": True, "status": "welcome"})

        if text == "/buystars":
            _telegram_send(
                chat_id,
                "💎 **Buy Telegram Stars**\n\n"
                "You need ⭐ Stars to subscribe to Tox Detector Premium.\n\n"
                "Tap the button below to purchase Stars through Telegram 👇",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "⭐ Buy Stars", "url": BUY_STARS_URL}
                    ]]
                },
            )
            return jsonify({"ok": True, "status": "buystars_sent"})

        if text == "/subscribe":
            ok = _send_invoice(chat_id)
            if ok:
                return jsonify({"ok": True, "status": "invoice_sent"})
            _telegram_send(chat_id, "⚠️ Failed to create invoice. Please try again later.")
            return jsonify({"ok": False, "status": "invoice_failed"})


    # ── Check subscription before analysis ──
    if not can_analyze(user_id):
        # Explain why + what Premium includes + Buy Stars button
        _telegram_send(
            chat_id,
            "⚠️ **Free trial used up!**\n\n"
            "🔥 **Tox Detector Premium**\n"
            f"🌟 **{STAR_PRICE} ⭐ Stars** — valid for 30 days\n"
            "✅ Unlimited relationship analysis\n"
            "✅ Priority processing\n\n"
            "📩 Invoice sent below 👇",
        )
        # Send invoice directly — one step, no extra click
        ok = _send_invoice(chat_id)
        if not ok:
            _telegram_send(
                chat_id,
                "⚠️ Could not create invoice. Try /subscribe",
            )
        return jsonify({"ok": True, "status": "subscription_required"})

    # ── Buffer message for analysis ──
    speaker, name = _detect_speaker(msg)

    with _lock:
        is_first = chat_id not in _buffers
        if is_first:
            _buffers[chat_id] = {"entries": [], "timer": None}
            free_left = remaining_free(user_id)
            trial = ""
            if free_left > 0:
                trial = f" ({free_left} free trial left)"
            # Send immediately before any heavy operations
            _telegram_send(chat_id,
                f"🔵 Aggregating messages...{trial}")
        buf = _buffers[chat_id]
        buf["entries"].append({"text": msg.text, "speaker": speaker, "name": name})
        buf["user_id"] = user_id
        if buf["timer"] is not None:
            buf["timer"].cancel()
        timer = threading.Timer(2.0, _flush, args=[chat_id, user_id])
        timer.daemon = True
        timer.start()
        buf["timer"] = timer

    logger.info("Buffered for chat=%s user=%s (total %d)", chat_id, user_id, len(buf["entries"]))
    return jsonify({"ok": True, "status": "buffered"})


# ---------------------------------------------------------------------------
# Extra routes
# ---------------------------------------------------------------------------
@bp.route("/api/analysis/<analysis_id>")
def get_analysis(analysis_id: str):
    result = _analysis_store.pop(analysis_id, None)
    if result is None:
        return jsonify({"error": "Not found", "deleted": True}), 404
    return jsonify(result.model_dump())


@bp.route("/api/test_telegram")
def test_telegram():
    chat_id = request.args.get("chat_id", "")
    if not chat_id:
        return jsonify({"error": "Provide ?chat_id=YOUR_CHAT_ID"}), 400
    try:
        chat_id = int(chat_id)
    except ValueError:
        return jsonify({"error": "chat_id must be integer"}), 400
    ok = _telegram_send(chat_id, "🧪 Tox Detector diagnostic: all connections OK ✅")
    return jsonify({"sent": ok})
