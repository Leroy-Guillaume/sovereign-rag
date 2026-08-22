"""PII redaction for context passages that leave the infrastructure.

On the local profile nothing leaves, so the default is the no-op. On the
delegated profiles (openai_compatible, azure_openai) the retrieved passages
travel to the endpoint the operator configured; REDACTION_PROVIDER=patterns
masks direct identifiers before they do. Pattern-based on purpose: it runs
offline, adds no model download, and its behavior is exactly auditable.
Named-entity redaction (Presidio) stays on the roadmap; this seam is where
it will plug in.

Order matters: IBAN before Swiss AVS (an IBAN contains digit runs an AVS
pattern could partially claim), specific before generic.
"""

import re
from collections.abc import Callable
from typing import Literal

RedactionProvider = Literal["none", "patterns"]

# Each rule: (label, compiled pattern). The mask keeps the label visible so
# an answer citing a redacted passage says WHAT was removed.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")),
    # IBAN: two letters, two check digits, 11 to 30 alphanumerics, spaces allowed.
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{2,4}){3,8}\b")),
    # Swiss AVS/AHV number: 756.XXXX.XXXX.XX, dots or spaces.
    ("avs", re.compile(r"\b756[.\s]\d{4}[.\s]\d{4}[.\s]\d{2}\b")),
    # Phone numbers: international or Swiss national format, 9+ digits total,
    # allowing spaces, dots, dashes and a parenthesized prefix.
    (
        "phone",
        re.compile(
            r"(?<![\w.])(?:\+|00)\d{2}[\s./-]?(?:\(0\))?(?:[\s./-]?\d{1,4}){3,6}\b"
            r"|(?<![\w.])0\d{2}[\s./-]\d{3}[\s./-]\d{2}[\s./-]\d{2}\b"
        ),
    ),
]


def redact_patterns(text: str) -> str:
    """Mask direct identifiers, keeping a typed placeholder per hit."""
    for label, pattern in _RULES:
        text = pattern.sub(f"[{label} redacted]", text)
    return text


def create_redactor(provider: RedactionProvider) -> Callable[[str], str]:
    """The identity for "none": callers always get a callable to pass along."""
    match provider:
        case "none":
            return lambda text: text
        case "patterns":
            return redact_patterns
