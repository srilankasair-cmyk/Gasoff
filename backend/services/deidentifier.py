"""De-identification service: strips PII from chat messages while preserving structure.

Covers: phones, emails, IDs, addresses, names, URLs, IPs, dates, bank cards,
license plates, and generic number strings. Supports both Chinese and English.
"""

import re
from typing import Tuple
from backend.models.schemas import DeidentificationResult, DeidentifiedSegment

# ═══════════════════════════════════════════════════════════════════════
# Patterns — ordered from most specific to least specific
# ═══════════════════════════════════════════════════════════════════════

# ── URLs & IPs ──
_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+|ftp://[^\s<>\"']+",
    re.IGNORECASE,
)
_IP_PATTERN = re.compile(
    r"\b(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\."
    r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\."
    r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\."
    r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\b"
)

# ── Email ──
_EMAIL_PATTERN = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]{2,}",
    re.IGNORECASE,
)

# ── Phone numbers ──
# Chinese mobile: 1[3-9] followed by 9 digits
_CN_MOBILE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# International format: +86 13812345678, +1 (555) 123-4567, etc.
_INTL_PHONE_PATTERN = re.compile(r"\+\d{1,3}[\d\s\-().]{6,}\d")
# US/domestic common formats: (555) 123-4567, 555-123-4567, 555.123.4567
_DOMESTIC_PHONE_PATTERN = re.compile(
    r"(?<!\d)\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)"
)
# Chinese landline: 0XXX-XXXXXXXX or 0XXXX-XXXXXXX
_CN_LANDLINE_PATTERN = re.compile(r"(?<!\d)0\d{2,3}[-.\s]?\d{7,8}(?!\d)")

# ── Financial ──
# Credit / debit card: groups of 4 digits
_BANK_CARD_PATTERN = re.compile(
    r"(?<!\d)\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)"
)
# Chinese bank card: 16-19 digits
_CN_BANK_CARD_PATTERN = re.compile(r"(?<!\d)(?:62|60|55|53|52|51|50|49|45|44|43|42|41|40)\d{14,17}(?!\d)")

# ── Chinese national ID (18 digits: birth date + checksum) ──
_CN_ID_PATTERN = re.compile(
    r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
)

# ── License plates ──
# Chinese: province char + city letter + 5-6 alphanum
_CN_PLATE_PATTERN = re.compile(
    r"(?<!\w)[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁][A-Z][A-Z0-9]{4,6}(?!\w)"
)

# ── Addresses ──
# English street addresses
_EN_ADDRESS_PATTERN = re.compile(
    r"\b\d{1,6}\s+[\w\s]+?\s(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Lane|Ln\.?|"
    r"Drive|Dr\.?|Boulevard|Blvd\.?|Court|Ct\.?|Way|Place|Pl\.?|Circle|Cir\.?|"
    r"Highway|Hwy\.?|Parkway|Pkwy\.?|Square|Sq\.?)\b(?:,?\s+\w+(?:\s+\w+)*)?",
    re.IGNORECASE,
)
# Chinese addresses: province/city/district/road/number patterns
# Uses {2,} to capture multi-level addresses; may over-catch slightly
# but that's acceptable for privacy (better to remove more than less)
_CN_ADDRESS_PATTERN = re.compile(
    r"[一-鿿]{2,}(?:省|自治区|市|区|县|镇|乡|村|路|街|巷|弄|大道|大街)"
    r"(?:[一-鿿]{2,}(?:路|街|巷|弄|大道|大街))?"
    r"(?:\d{1,6}号(?:\d{1,4}楼\d{1,4}室?)?)?"
)
# PO Box
_PO_BOX_PATTERN = re.compile(
    r"\bP\.?O\.?\s*Box\s+\d+\b", re.IGNORECASE
)

# ── Dates (full dates that could identify) ──
_DATE_PATTERN = re.compile(
    r"(?<!\d)\d{4}[-/年月]\d{1,2}[-/月日]\d{1,2}[日]?(?!\d)|"
    r"(?<!\d)\d{1,2}[-/]\d{1,2}[-/]\d{4}(?!\d)|"
    r"(?<!\d)\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}(?!\d)",
    re.IGNORECASE,
)

# ── Generic number strings (catch-all for IDs, order numbers, etc.) ──
# 6+ digit numbers not already matched by more specific patterns
_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{6,}(?!\d)")

# ── Telegram @username ──
_NAME_PATTERN = re.compile(r"@\w+")

# ═══════════════════════════════════════════════════════════════════════
# Ordered list — run in priority order (most specific first)
# ═══════════════════════════════════════════════════════════════════════
_PATTERNS: list[Tuple[re.Pattern, str]] = [
    (_URL_PATTERN, "url"),
    (_IP_PATTERN, "ip"),
    (_EMAIL_PATTERN, "email"),
    (_CN_MOBILE_PATTERN, "phone"),
    (_INTL_PHONE_PATTERN, "phone"),
    (_DOMESTIC_PHONE_PATTERN, "phone"),
    (_CN_LANDLINE_PATTERN, "phone"),
    (_BANK_CARD_PATTERN, "bank_card"),
    (_CN_BANK_CARD_PATTERN, "bank_card"),
    (_CN_ID_PATTERN, "id_card"),
    (_CN_PLATE_PATTERN, "plate"),
    (_EN_ADDRESS_PATTERN, "address"),
    (_CN_ADDRESS_PATTERN, "address"),
    (_PO_BOX_PATTERN, "address"),
    (_DATE_PATTERN, "date"),
    (_NUMBER_PATTERN, "number"),
    (_NAME_PATTERN, "name"),
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
