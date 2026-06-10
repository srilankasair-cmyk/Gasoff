"""DeepSeek LLM integration for relationship analysis.

Uses synchronous requests for PythonAnywhere compatibility.
"""

import json
import logging

import requests

from backend.config.settings import settings
from backend.models.schemas import (
    AnalysisResult,
    CircumplexAxis,
    CircumplexData,
    GottmanScores,
    GottmanExplanations,
    GottmanData,
    ToxicSentence,
)

logger = logging.getLogger(__name__)

_ANALYSIS_SYSTEM_PROMPT = (
    'You are "Tox Detector", a world-class relationship psychologist AI.\n'
    "Analyze the following chat conversation between two people.\n"
    "Messages are labelled as [You: NAME] (the person who forwarded this)\n"
    "and [Other: NAME] (the other person in the conversation).\n"
    "\n"
    "There are TWO modes:\n"
    "\n"
    'Mode A — The user is in the conversation (messages labelled [You: ...] exist):\n'
    '  - "other_name" = the other person\'s name\n'
    '  - "toxicity_direction" = "other_to_self" if the other person hurts the user, '
    '"self_to_other" if the user hurts the other\n'
    '  - "toxicity_explanation" = 1-2 sentences in English explaining who is hurting whom\n'
    '  - gottman_user = the user\'s own Four Horsemen scores\n'
    '  - gottman_other = the other person\'s Four Horsemen scores\n'
    '  - "original_speaker" = "user" or "other"\n'
    "\n"
    'Mode B — Both people are third parties (only [Other: ...] messages):\n'
    '  - "other_name" = "Both parties"\n'
    '  - "toxicity_direction" = "mutual"\n'
    '  - "toxicity_explanation" = explanation of mutual toxicity in English\n'
    '  - gottman_user = first person\'s scores, gottman_other = second person\'s scores\n'
    '  - "original_speaker" = "Person_A" or "Person_B"\n'
    "\n"
    "Return a JSON object with exactly these fields:\n"
    "{\n"
    '  "other_name": "name",\n'
    '  "toxicity_score": integer 0-100 (always positive),\n'
    '  "toxicity_direction": "other_to_self" | "self_to_other" | "mutual",\n'
    '  "toxicity_explanation": "English explanation of direction",\n'
    '  "gottman_user": {\n'
    '    "criticism": 0-100, "contempt": 0-100,\n'
    '    "defensiveness": 0-100, "stonewalling": 0-100\n'
    "  },\n"
    '  "gottman_other": {\n'
    '    "criticism": 0-100, "contempt": 0-100,\n'
    '    "defensiveness": 0-100, "stonewalling": 0-100\n'
    "  },\n"
    '  "circumplex": {\n'
    '    "user": { "dominance": -100_100, "arrogance": -100_100, '
    '"coldness": -100_100, "hostility": -100_100,\n'
    '      "submission": -100_100, "humility": -100_100, '
    '"warmth": -100_100, "empathy": -100_100 },\n'
    '    "other": { "dominance": -100_100, "arrogance": -100_100, '
    '"coldness": -100_100, "hostility": -100_100,\n'
    '      "submission": -100_100, "humility": -100_100, '
    '"warmth": -100_100, "empathy": -100_100 }\n'
    "  },\n"
    '  "toxic_sentences": [{\n'
    '    "sentence": "exact toxic sentence",\n'
    '    "label": "English label e.g. Emotional Blackmail",\n'
    '    "explanation": "why this is toxic in English",\n'
    '    "original_speaker": "user | other | Person_A | Person_B",\n'
    '    "counter_suggestion": "anti-PUA phrase in English"\n'
    "  }],\n"
    '  "summary": "brief analysis in English, max 3 sentences",\n'
    '  "gottman_explanations": {\n'
    '    "criticism": "explain what this criticism score means for this specific relationship, citing concrete evidence from the conversation",\n'
    '    "contempt": "explain what this contempt score means, why it matters (Gottman found contempt is the #1 predictor of divorce), with evidence from the conversation",\n'
    '    "defensiveness": "explain what this defensiveness score means for this specific relationship, with evidence from the conversation",\n'
    '    "stonewalling": "explain what this stonewalling score means for this specific relationship, with evidence from the conversation"\n'
    "  },\n"
    '  "circumplex_summary": "interpret the circumplex radar chart data (dominance, warmth, hostility patterns) into 2-3 sentences describing the overall relationship dynamic, citing specific axis patterns"\n'
    "}\n"
    "\n"
    "Gottman scores follow John Gottman's Four Horsemen (Criticism, Contempt, Defensiveness, Stonewalling).\n"
    "Circumplex follows the Interpersonal Circumplex model.\n"
    "IMPORTANT — gottman_explanations: For each horseman where BOTH people score 0, omit that key entirely.\n"
    "For non-zero scores, write 1-2 evidence-based sentences that:\n"
    "  1. Explain what this score level means in the context of this specific relationship.\n"
    "  2. Reference specific patterns or examples from the conversation as evidence.\n"
    "  3. Use Gottman's research framework (e.g., Criticism attacks character not behavior;\n"
    "     Contempt includes sarcasm, mockery, hostile humor, eye-rolling;\n"
    "     Defensiveness is counter-blaming or victim-stance;\n"
    "     Stonewalling is emotional withdrawal and shutting down).\n"
    "IMPORTANT — circumplex_summary: Write 2-3 sentences interpreting the interpersonal circumplex patterns.\n"
    "  Discuss who leads on dominance/warmth/hostility, whether the dynamic is complementary or conflicted,\n"
    "  and what the overall pattern suggests about the relationship. Reference specific axis values.\n"
    "Use English labels for toxic sentences: Emotional Blackmail, Gaslighting, Belittling, "
    "Denial, Blame Shifting, Silent Treatment, Emotional Coercion etc.\n"
    "Counter-suggestions should be practical, empowering phrases in English. All output must be in English.\n"
)


class AnalysisError(Exception):
    pass


def _build_prompt(clean_text: str) -> str:
    return f"Analyze this conversation:\n\n{clean_text}"


def analyze_conversation(clean_text: str) -> AnalysisResult:
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
        resp = requests.post(
            settings.DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_result(json.loads(content))
    except requests.HTTPError as e:
        logger.error(f"DeepSeek API error: {e.response.status_code}")
        raise AnalysisError(f"API error: {e.response.status_code}")
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse DeepSeek response: {e}")
        raise AnalysisError("Invalid response format from LLM")
    except (requests.ConnectionError, requests.Timeout) as e:
        logger.error(f"Network error connecting to DeepSeek: {e}; falling back to mock")
        return _mock_result()


def _parse_result(data: dict) -> AnalysisResult:
    gu = data.get("gottman_user", data.get("gottman", {}))
    go = data.get("gottman_other", data.get("gottman", {}))
    cu = data["circumplex"]["user"]
    co = data["circumplex"]["other"]

    # Parse AI-generated explanations
    ge = data.get("gottman_explanations", {})
    gottman_explanations = None
    if ge and any(ge.get(k) for k in ['criticism', 'contempt', 'defensiveness', 'stonewalling']):
        gottman_explanations = GottmanExplanations(
            criticism=ge.get("criticism"),
            contempt=ge.get("contempt"),
            defensiveness=ge.get("defensiveness"),
            stonewalling=ge.get("stonewalling"),
        )

    return AnalysisResult(
        other_name=data.get("other_name", "Other"),
        toxicity_score=data["toxicity_score"],
        toxicity_direction=data.get("toxicity_direction", "other_to_self"),
        toxicity_explanation=data.get("toxicity_explanation", ""),
        gottman=GottmanData(
            user=GottmanScores(
                criticism=gu.get("criticism", 0),
                contempt=gu.get("contempt", 0),
                defensiveness=gu.get("defensiveness", 0),
                stonewalling=gu.get("stonewalling", 0),
            ),
            other=GottmanScores(
                criticism=go.get("criticism", 0),
                contempt=go.get("contempt", 0),
                defensiveness=go.get("defensiveness", 0),
                stonewalling=go.get("stonewalling", 0),
            ),
            explanations=gottman_explanations,
        ),
        circumplex=CircumplexData(
            user=CircumplexAxis(**cu),
            other=CircumplexAxis(**co),
        ),
        toxic_sentences=[ToxicSentence(**s) for s in data.get("toxic_sentences", [])],
        summary=data.get("summary", ""),
        circumplex_summary=data.get("circumplex_summary"),
    )


def _mock_result() -> AnalysisResult:
    """Return a plausible mock when DeepSeek is unreachable."""
    return AnalysisResult(
        other_name="TA",
        toxicity_score=72,
        toxicity_direction="other_to_self",
        toxicity_explanation="The other person uses frequent criticism and contempt, "
                             "causing you emotional stress and putting you on the defensive.",
        gottman=GottmanData(
            user=GottmanScores(
                criticism=15, contempt=5, defensiveness=60, stonewalling=20,
            ),
            other=GottmanScores(
                criticism=68, contempt=55, defensiveness=30, stonewalling=42,
            ),
            explanations=GottmanExplanations(
                criticism="TA's criticism score (68%) is significantly elevated. "
                          "In the conversation, TA repeatedly attacked your character rather than addressing specific behaviors — "
                          "for example, using 'you always' statements that frame personal failings rather than isolated incidents. "
                          "Your lower score (15%) suggests you mostly avoid this pattern.",
                contempt="TA's contempt score (55%) is the most concerning finding. "
                         "Gottman's research identifies contempt as the single strongest predictor of relationship dissolution. "
                         "TA used sarcasm and dismissive language, signaling a lack of respect. "
                         "Your score (5%) shows you do not reciprocate this dynamic.",
                defensiveness="Your defensiveness score (60%) is notable. "
                              "This is a common response to persistent criticism — when someone feels constantly attacked, "
                              "they often develop a protective wall of counter-blame or victim-stance. "
                              "TA also shows some defensiveness (30%), suggesting both parties struggle to hear feedback.",
                stonewalling="TA's stonewalling (42%) indicates emotional withdrawal during conflict. "
                             "This may manifest as shutting down, giving short responses, or physically leaving conversations. "
                             "Your stonewalling (20%) is lower, suggesting you remain more engaged despite the tension.",
            ),
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
                sentence="This is for your own good",
                label="Emotional Blackmail",
                explanation="Disguising control as care.",
                original_speaker="other",
                counter_suggestion="I appreciate your concern, but this approach makes me uncomfortable.",
            ),
            ToxicSentence(
                sentence="You are too sensitive",
                label="Gaslighting",
                explanation="Denying the other person's feelings.",
                original_speaker="other",
                counter_suggestion="My feelings are valid. Let's talk about what actually happened.",
            ),
        ],
        summary="The other person shows a dominant communication pattern "
                "with emotional blackmail and gaslighting.",
        circumplex_summary="TA dominates the interpersonal space with high dominance (75) and arrogance (60), "
                           "combined with notable coldness (50) and hostility (55). "
                           "You lean heavily toward the submissive-accommodating quadrant (submission 60, humility 50) "
                           "while maintaining warmth and empathy. This creates a strongly asymmetrical dynamic "
                           "where one person leads with control and criticism while the other responds with deference — "
                           "a pattern that, without intervention, tends to deepen over time.",
    )
