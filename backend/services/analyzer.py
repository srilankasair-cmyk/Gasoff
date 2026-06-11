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
    HorsemenDetail,
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
    '  - gottman_user = the user\'s own Four Horsemen scores\n'
    '  - gottman_other = the other person\'s Four Horsemen scores\n'
    '  - "original_speaker" = "user" or "other"\n'
    "\n"
    'Mode B — Both people are third parties (only [Other: ...] messages):\n'
    '  - "other_name" = "Both parties"\n'
    '  - "toxicity_direction" = "mutual"\n'
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
    '  "toxic_sentences": [\n'
    '    // EXHAUSTIVE: list EVERY toxic sentence found. No cherry-picking. All of them.\n'
    '    {\n'
    '      "sentence": "exact toxic sentence",\n'
    '      "label": "English label e.g. Emotional Blackmail",\n'
    '      "explanation": "why this is toxic in English",\n'
    '      "original_speaker": "user | other | Person_A | Person_B",\n'
    '      "counter_suggestion": "anti-PUA phrase in English"\n'
    "    }\n"
    "  ],\n"
    '  "summary": "brief analysis in English, max 3 sentences",\n'
    '  "gottman_explanations": {\n'
    '    "criticism": {\n'
    '      "colloquial_meaning": "explain what this score means in plain, relatable English — no academic jargon",\n'
    '      "captured_quote": "exact sentence from the conversation that best illustrates this pattern",\n'
    '      "verdict": "sharp, empathetic, wake-up-call diagnosis. Lock onto the specific chat evidence. '
    'Use modern relatable language. Call out manipulation patterns directly.",\n'
    '      "counter_strategy": "practical one-sentence response script the user can actually use"\n'
    "    },\n"
    '    "contempt": { ... same structure ... },\n'
    '    "defensiveness": { ... same structure ... },\n'
    '    "stonewalling": { ... same structure ... }\n'
    "  },\n"
    '  "circumplex_summary": "2-3 paragraphs interpreting the circumplex radar chart. '
    'Separate paragraphs with a blank line. Each paragraph MUST start with a bold title line ending with a colon '
    '(e.g. Power Dynamic: One-Sided Control), then IPC grounding, a captured quote, and a verdict. '
    'DO NOT use confusing terms like \'red spikes\' or \'blue shrinks\' — use actual names or You/Other."\n'
    "}\n"
    "\n"
    "=== VISUAL REPORT INTERPRETATION SPEC ===\n"
    "Gottman scores follow John Gottman's Four Horsemen. Circumplex follows the IPC model.\n"
    "\n"
    "CRITICAL — gottman_explanations: For each horseman, produce a structured object with 4 fields:\n"
    "  1. colloquial_meaning: Plain English, relatable. What does this score actually mean?\n"
    '     e.g. "Your partner does not respect you as an equal. They tear down your self-worth to fuel their own ego."\n'
    "  2. captured_quote: Copy-paste the most damning sentence from the conversation verbatim.\n"
    "  3. verdict: The sharp diagnosis. Call out manipulation, gaslighting, power moves. Use bold, empathetic language.\n"
    '     e.g. "This is not a regular argument — this is character assassination. Wake up."\n'
    "  4. counter_strategy: One practical, empowering script the user can say. Short and actionable.\n"
    "\n"
    "OMIT a horseman key entirely only if BOTH people score 0 on it.\n"
    "Order horsemen from HIGHEST combined score to LOWEST.\n"
    "\n"
    "Gottman research framework — use these correctly:\n"
    "  - Criticism: attacks character/personality, not specific behavior. Uses 'you always/never' absolutes.\n"
    "  - Contempt: #1 predictor of divorce. Includes sarcasm, mockery, hostile humor, eye-rolling, sneering.\n"
    "  - Defensiveness: counter-blaming, playing victim, refusing accountability. 'I only did X because YOU did Y.'\n"
    "  - Stonewalling: emotional withdrawal, silent treatment, one-word replies, physically leaving, going ghost.\n"
    "\n"
    "CRITICAL — circumplex_summary: Write 2-3 paragraphs, separated by blank lines. Each paragraph:\n"
    "  MUST start with a bold title line ending with a colon, on its own line.\n"
    '    Good examples: "Power Dynamic: One-Sided Control", "Emotional Temperature: Warmth Meets a Cold Wall",\n'
    '    "Relationship Pattern: Complementary but Unequal"\n'
    "    DO NOT use confusing \'red spikes\' or \'blue shrinks\' — use You/Other person labels instead.\n"
    "  Then include: IPC grounding, a captured quote, and a verdict-style interpretation.\n"
    "  Use vivid, relatable metaphors (e.g. 'hijacked the steering wheel', 'emotional black hole').\n"
    "\n"
    "TONE RULES:\n"
    "  - NO academic jargon like 'orthogonal vectors', 'cascading emotional disengagement', etc.\n"
    "  - Use modern, relatable English. Write like a sharp therapist who genuinely cares.\n"
    "  - Be empathetic toward the victim. Call out the aggressor directly.\n"
    "\n"
    "CRITICAL — toxic_sentences: You MUST exhaustively list EVERY toxic or manipulative sentence "
    "in the conversation. Do not cherry-pick or limit to a few examples — be thorough and complete. "
    "If there are 10 toxic sentences, list all 10. If there are 20, list all 20. "
    "Each toxic_sentence must include: the exact sentence, a descriptive label, "
    "a 1-sentence explanation of why it's toxic, the original speaker, and a practical counter-suggestion.\n"
    "\n"
    "Use English labels for toxic sentences: Emotional Blackmail, Gaslighting, Belittling, "
    "Denial, Blame Shifting, Silent Treatment, Emotional Coercion, Guilt Tripping, "
    "Threat, Humiliation, Dismissiveness, Sarcasm, Name Calling, Love Withdrawal, "
    "Victim Reversal, Minimization, Trivialization, Isolation, Control etc.\n"
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

    # Parse AI-generated explanations (structured HorsemenDetail format)
    ge = data.get("gottman_explanations", {})
    gottman_explanations = None
    if ge:
        details = {}
        for key in ['criticism', 'contempt', 'defensiveness', 'stonewalling']:
            item = ge.get(key)
            if item and isinstance(item, dict):
                details[key] = HorsemenDetail(
                    colloquial_meaning=item.get("colloquial_meaning", ""),
                    captured_quote=item.get("captured_quote", ""),
                    verdict=item.get("verdict", ""),
                    counter_strategy=item.get("counter_strategy", ""),
                )
            elif item and isinstance(item, str):
                # Backward-compat: plain string → use as verdict
                details[key] = HorsemenDetail(verdict=item)
        if details:
            gottman_explanations = GottmanExplanations(**details)

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
                criticism=HorsemenDetail(
                    colloquial_meaning="TA attacks who you are, not what you did. Every disagreement becomes a trial of your character.",
                    captured_quote="You never use your brain. You are just a fundamentally selfish person.",
                    verdict="This is not feedback — this is identity erosion. Absolute labels like 'you never' and 'you are just a...' are not about solving problems; they hand down a life sentence on who you are as a person.",
                    counter_strategy="We're talking about one specific event. Don't escalate this into a judgment of my character.",
                ),
                contempt=HorsemenDetail(
                    colloquial_meaning="TA does not respect you as an equal. They mock and belittle you to prop up their own fragile ego.",
                    captured_quote="Lol, with the tiny salary you make, do you honestly think you could survive without me?",
                    verdict="This is the most dangerous horseman. Gottman identified contempt as the #1 predictor of relationship failure. TA is systematically eroding your confidence so you feel helpless — someone who loves you would never step on your dignity.",
                    counter_strategy="My ability to survive is not yours to define. This conversation is over.",
                ),
                defensiveness=HorsemenDetail(
                    colloquial_meaning="TA plays the ultimate Teflon communicator — nothing sticks. They never accept blame, always twist reality to play the victim.",
                    captured_quote="If you hadn't talked to that person yesterday, I wouldn't have lost my temper. You literally pushed me to do this.",
                    verdict="Classic gaslighting. TA shifts accountability for their own rage onto you, framing it as 'punishment for your mistake.' If you start apologizing or second-guessing yourself, they win.",
                    counter_strategy="Take responsibility for your own emotions. Don't blame your lack of self-control on my actions.",
                ),
                stonewalling=HorsemenDetail(
                    colloquial_meaning="TA uses the silent treatment as a weapon — disappearing to punish you and force you to beg for forgiveness.",
                    captured_quote="Ok. / Whatever, think what you want. (then goes silent for hours)",
                    verdict="This is a cruel power move designed to manufacture abandonment anxiety. By cutting off the emotional oxygen, they trick your brain into panic mode, forcing you to compromise your boundaries just to get a response.",
                    counter_strategy="Stop typing. Close the app. Your energy does not belong in an empty digital abyss.",
                ),
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
