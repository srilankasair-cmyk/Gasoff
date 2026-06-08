"""De-identification service: strips PII from chat messages while preserving structure."""

import re
from typing import Tuple
from backend.models.schemas import DeidentificationResult, DeidentifiedSegment


# Compiled patterns for performance
_NAME_PATTERN = re.compile(r"@\w+")  # Telegram usernames
_PHONE_PATTERN = re.compile(r"\+?\d[\d\s\-().]{6,}\d")
_EMAIL_PATTERN = re.compile(r"[\w.]+@[\w.]+\.\w{2,}")
_ADDRESS_PATTERN = re.compile(
    r"\d{1,5}\s+\w+\s+(Street|St|Road|Rd|Ave|Avenue|Lane|Ln|Drive|Dr|Boulevard|Blvd|"
    r"路|街|巷|大道|弄)",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}|"
    r"\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}",
    re.IGNORECASE,
)
_NUMBER_PATTERN = re.compile(r"\b\d{6,}\b")  # IDs, order numbers etc.


# Ordered so names & contact info are stripped before addresses
_PATTERNS: list[Tuple[re.Pattern, str]] = [
    (_NAME_PATTERN, "name"),
    (_PHONE_PATTERN, "phone"),
    (_EMAIL_PATTERN, "email"),
    (_ADDRESS_PATTERN, "address"),
    (_DATE_PATTERN, "date"),
    (_NUMBER_PATTERN, "number"),
]


def deidentify(text: str) -> DeidentificationResult:
    """Strip identifiable info, return clean text and a list of replaced segments."""
    segments: list[DeidentifiedSegment] = []

    for pattern, ptype in _PATTERNS:
        def replacer(m: re.Match, t=ptype) -> str:
            placeholder = f"[{t.upper()}_{len(segments)+1}]"
            segments.append(
                DeidentifiedSegment(
                    original=m.group(0),
                    placeholder=placeholder,
                    type=t,
                )
            )
            return placeholder

        text = re.sub(pattern, replacer, text)

    return DeidentificationResult(clean_text=text, segments=segments)
