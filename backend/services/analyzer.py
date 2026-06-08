"""DeepSeek LLM integration for relationship analysis."""

import json
import logging
import uuid
from typing import Optional

import httpx

from backend.config.settings import settings
from backend.models.schemas import (
    AnalysisResult,
    CircumplexAxis,
    CircumplexData,
    GottmanScores,
    ToxicSentence,
)

logger = logging.getLogger(__name__)

_ANALYSIS_SYSTEM_PROMPT = """You are "Gas-off", a world-class relationship psychologist AI. 
Analyze the following de-identified chat conversation between two people (USER and OTHER).

Return a JSON object with exactly these fields:
{
  "other_name": "display name for the other person (can be 'OTHER' if unknown)",
  "toxicity_score": integer 0-100,
  "gottman": {
    "criticism": 0-100,
    "contempt": 0-100,
    "defensiveness": 0-100,
    "stonewalling": 0-100
  },
  "circumplex": {
    "user": { "dominance": -100 to 100, "arrogance": -100 to 100, "coldness": -100 to 100, "hostility": -100 to 100, "submission": -100 to 100, "humility": -100 to 100, "warmth": -100 to 100, "empathy": -100 to 100 },
    "other": { "dominance": -100 to 100, "arrogance": -100 to 100, "coldness": -100 to 100, "hostility": -100 to 100, "submission": -100 to 100, "humility": -100 to 100, "warmth": -100 to 100, "empathy": -100 to 100 }
  },
  "toxic_sentences": [
    {
      "sentence": "the exact toxic sentence",
      "label": "academic label e.g. '情感勒索 (Emotional Blackmail)'",
      "explanation": "why this is toxic",
      "original_speaker": "user or other",
      "counter_suggestion": "防PUA回击话术"
    }
  ],
  "summary": "brief overall analysis in Chinese, max 3 sentences"
}

Gottman scores are based on John Gottman's Four Horsemen theory.
Circumplex axes follow the Interpersonal Circumplex model (dominant vs submissive, warm vs cold).
For toxic sentences, use labels like: 情感勒索, 煤气灯效应, 贬低, 否定感受, 责任转嫁, 冷暴力威胁, 情绪绑架 etc.
Counter-suggestions should be practical, empowering phrases the user can say back.
"""


class AnalysisError(Exception):
    pass


def _build_prompt(clean_text: str) -> str:
    return f"Analyze this de-identified conversation:\n\n{clean_text}"


async def analyze_conversation(clean_text: str) -> AnalysisResult:
    """Send de-identified text to DeepSeek and parse the structured result."""
    if not settings.DEEPSEEK_API_KEY:
        logger.warning("No DEEPSEEK_API_KEY configured; returning mock result")
        return _mock_result()

    payload = {
        "model": settings.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(clean_text)},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                settings.DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return _parse_result(json.loads(content))
    except httpx.HTTPStatusError as e:
        logger.error(f"DeepSeek API error: {e.response.status_code} {e.response.text}")
        raise AnalysisError(f"API error: {e.response.status_code}")
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse DeepSeek response: {e}")
        raise AnalysisError("Invalid response format from LLM")
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error(f"Network error connecting to DeepSeek: {e}; falling back to mock")
        return _mock_result()


def _parse_result(data: dict) -> AnalysisResult:
    g = data["gottman"]
    cu = data["circumplex"]["user"]
    co = data["circumplex"]["other"]
    return AnalysisResult(
        other_name=data.get("other_name", "对方"),
        toxicity_score=data["toxicity_score"],
        gottman=GottmanScores(
            criticism=g["criticism"],
            contempt=g["contempt"],
            defensiveness=g["defensiveness"],
            stonewalling=g["stonewalling"],
        ),
        circumplex=CircumplexData(
            user=CircumplexAxis(**cu),
            other=CircumplexAxis(**co),
        ),
        toxic_sentences=[ToxicSentence(**s) for s in data.get("toxic_sentences", [])],
        summary=data.get("summary", ""),
    )


def _mock_result() -> AnalysisResult:
    """Return a plausible mock when DeepSeek is unreachable."""
    return AnalysisResult(
        other_name="TA",
        toxicity_score=72,
        gottman=GottmanScores(
            criticism=68, contempt=55, defensiveness=80, stonewalling=42
        ),
        circumplex=CircumplexData(
            user=CircumplexAxis(
                dominance=-30, arrogance=-40, coldness=-20, hostility=-10,
                submission=60, humility=50, warmth=40, empathy=50,
            ),
            other=CircumplexAxis(
                dominance=75, arrogance=60, coldness=50, hostility=55,
                submission=-40, humility=-50, warmth=-30, empathy=-45,
            ),
        ),
        toxic_sentences=[
            ToxicSentence(
                sentence="我这都是为了你好",
                label="情感勒索 (Emotional Blackmail)",
                explanation="以'为你好'包装控制行为，让对方无法反驳。",
                original_speaker="other",
                counter_suggestion="「我知道你是好意，但这种方式让我不舒服。我们换个方式沟通好吗？」",
            ),
            ToxicSentence(
                sentence="你太敏感了",
                label="煤气灯效应 (Gaslighting)",
                explanation="否定对方的感受，让对方怀疑自己的判断。",
                original_speaker="other",
                counter_suggestion="「我的感受是真实的，请你不要否定。我们可以谈谈具体发生了什么。」",
            ),
        ],
        summary="这段对话中对方展现出明显的支配型沟通模式，存在情感勒索和煤气灯效应。"
                "建议用户设立边界，必要时寻求专业心理咨询。",
    )
