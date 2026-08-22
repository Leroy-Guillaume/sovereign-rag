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

RedactionProvider = Literal["none", "patterns", "ner"]

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


# Deterministic language guess for the NER pass: count stopword hits per
# language, majority wins, English by default. Auditable and dependency-free;
# the redaction bench reports its accuracy alongside the engines.
_STOPWORDS: dict[str, frozenset[str]] = {
    "fr": frozenset(
        "le la les des une et dans pour que qui sur sont aux cette".split()  # noqa: SIM905
    ),
    "de": frozenset(
        "der die das und nicht mit ist von den einer werden oder auch".split()  # noqa: SIM905
    ),
    "en": frozenset(
        "the of and to in for is that with on are this which shall".split()  # noqa: SIM905
    ),
}
_WORD = re.compile(r"[a-zà-üä-öß]+")


def guess_language(text: str) -> str:
    words = _WORD.findall(text.casefold())
    scores = {
        lang: sum(1 for word in words if word in stopwords)
        for lang, stopwords in _STOPWORDS.items()
    }
    best = max(scores, key=lambda lang: scores[lang])
    return best if scores[best] > 0 else "en"


def redact_patterns(text: str) -> str:
    """Mask direct identifiers, keeping a typed placeholder per hit."""
    for label, pattern in _RULES:
        text = pattern.sub(f"[{label} redacted]", text)
    return text


def _build_ner_redactor() -> Callable[[str], str]:
    """Patterns first, then PERSON-only NER in the guessed language.

    The measured configuration (bench/results/2026-08-redaction.md): names
    99 %, direct identifiers 100 %, 2 % false positives on clean legal text,
    ~6 ms per text. PERSON-only on purpose: full NER redaction rewrites 47 %
    of clean legal passages (law names, institutions), which would destroy
    the very context the product cites. Requires the pii extra.
    """
    try:
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "REDACTION_PROVIDER=ner requires the pii extra: uv sync --extra pii"
        ) from exc

    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": "fr", "model_name": "fr_core_news_md"},
                {"lang_code": "de", "model_name": "de_core_news_md"},
                {"lang_code": "en", "model_name": "en_core_web_md"},
            ],
        }
    )
    registry = RecognizerRegistry(supported_languages=["fr", "de", "en"])
    registry.load_predefined_recognizers(languages=["fr", "de", "en"])
    analyzer = AnalyzerEngine(
        nlp_engine=provider.create_engine(),
        registry=registry,
        supported_languages=["fr", "de", "en"],
    )

    def run(text: str) -> str:
        masked = redact_patterns(text)
        spans = analyzer.analyze(text=masked, language=guess_language(masked))
        for span in sorted(spans, key=lambda result: result.start, reverse=True):
            if span.entity_type in ("PERSON", "PER"):
                masked = masked[: span.start] + "[name redacted]" + masked[span.end :]
        return masked

    return run


def create_redactor(provider: RedactionProvider) -> Callable[[str], str]:
    """The identity for "none": callers always get a callable to pass along."""
    match provider:
        case "none":
            return lambda text: text
        case "patterns":
            return redact_patterns
        case "ner":
            return _build_ner_redactor()
