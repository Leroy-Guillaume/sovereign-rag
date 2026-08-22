# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "presidio-analyzer>=2.2,<3",
#   "spacy>=3.8,<3.9",
#   "fr-core-news-md @ https://github.com/explosion/spacy-models/releases/download/fr_core_news_md-3.8.0/fr_core_news_md-3.8.0-py3-none-any.whl",
#   "de-core-news-md @ https://github.com/explosion/spacy-models/releases/download/de_core_news_md-3.8.0/de_core_news_md-3.8.0-py3-none-any.whl",
#   "en-core-web-md @ https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl",
# ]
# ///
"""Measure redaction engines on the synthetic golden: recall, false positives, latency.

Engines:
  patterns  the shipped deterministic redactor (backend/src, imported in place)
  presidio  Presidio NER (spaCy md models fr/de/en) over its predefined recognizers
  both      patterns first, then presidio on the remainder (layered defense)
  llm       the local Ollama model rewrites the text (exploratory arm)

Scoring:
  recall     per entity type: the injected value no longer appears in the output
  clean FP   fraction of untouched corpus sentences an engine rewrites anyway
             (rewriting clean legal text destroys the passages the product cites)
  latency    mean per case

Usage: uv run bench/redaction_eval.py --engine patterns [--limit N]
"""

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.request
from collections import defaultdict
from collections.abc import Callable

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "backend" / "src"))

from sovereign_rag.redaction import guess_language, redact_patterns  # noqa: E402

_WS = re.compile(r"\s+")


def norm(text: str) -> str:
    return _WS.sub(" ", text).casefold()


def build_presidio(only: set[str] | None = None) -> Callable[[str, str], str]:
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NlpEngineProvider

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

    def run(text: str, lang: str) -> str:
        results = analyzer.analyze(text=text, language=lang)
        if only is not None:
            results = [r for r in results if r.entity_type in only]
        for span in sorted(results, key=lambda r: r.start, reverse=True):
            label = span.entity_type.lower()
            text = text[: span.start] + f"[{label} redacted]" + text[span.end :]
        return text

    return run


def build_llm() -> Callable[[str, str], str]:
    prompt = (
        "Rewrite the text, replacing every piece of personal data (person names, "
        "email addresses, phone numbers, postal addresses, IBAN, social security "
        "numbers, company names) with [redacted]. Change NOTHING else, keep the "
        "language of the text. Answer with the rewritten text only.\n\nText:\n{t}"
    )

    def run(text: str, lang: str) -> str:
        body = json.dumps(
            {
                "model": "qwen3:4b-instruct",
                "prompt": prompt.format(t=text),
                "stream": False,
                "options": {"temperature": 0},
            }
        ).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())["response"].strip()

    return run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--engine",
        choices=[
            "patterns",
            "presidio",
            "both",
            "person-layered",
            "person-union",
            "person-detect",
            "llm",
        ],
        required=True,
    )
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    golden = json.loads((HERE / "redaction_golden.json").read_text())
    cases, clean = golden["cases"], golden["clean"]
    if args.limit:
        cases, clean = cases[: args.limit], clean[: args.limit]

    if args.engine == "patterns":
        engine: Callable[[str, str], str] = lambda t, _lang: redact_patterns(t)  # noqa: E731
    elif args.engine == "presidio":
        engine = build_presidio()
    elif args.engine == "both":
        presidio = build_presidio()
        engine = lambda t, lang: presidio(redact_patterns(t), lang)  # noqa: E731
    elif args.engine == "person-detect":
        # The shipped variant: deterministic language guess, then PERSON-only
        # NER in that single language, layered over the patterns.
        person_d = build_presidio(only={"PERSON", "PER"})
        detect_ok = sum(1 for c in cases + clean if guess_language(c["text"]) == c["lang"])
        print(f"  language guess accuracy: {detect_ok}/{len(cases) + len(clean)}")
        engine = lambda t, _lang: person_d(redact_patterns(t), guess_language(t))  # noqa: E731
    elif args.engine == "person-union":
        # The production variant: at the LLM boundary the language is unknown,
        # so PERSON spans from all three analyses are unioned.
        person_u = build_presidio(only={"PERSON", "PER"})

        def union(text: str, _lang: str) -> str:
            masked = redact_patterns(text)
            for lang in ("fr", "de", "en"):
                masked = person_u(masked, lang)
            return masked

        engine = union
    elif args.engine == "person-layered":
        # Patterns for the direct identifiers, NER for PERSON only: names are
        # the actual gap; LOC/ORG detections are what shreds clean legal text.
        person = build_presidio(only={"PERSON", "PER"})
        engine = lambda t, lang: person(redact_patterns(t), lang)  # noqa: E731
    else:
        engine = build_llm()

    hits: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    t0 = time.time()
    for case in cases:
        masked = norm(engine(case["text"], case["lang"]))
        for entity in case["entities"]:
            totals[entity["type"]] += 1
            if norm(entity["value"]) not in masked:
                hits[entity["type"]] += 1
    per_case = (time.time() - t0) / len(cases)

    rewritten = sum(1 for c in clean if norm(engine(c["text"], c["lang"])) != norm(c["text"]))

    print(f"===== {args.engine} =====")
    print(f"  cases: {len(cases)} | clean: {len(clean)} | {per_case * 1000:.0f} ms/case")
    overall_hit = sum(hits.values())
    overall_tot = sum(totals.values())
    print(
        f"  recall overall : {overall_hit}/{overall_tot} ({100 * overall_hit / overall_tot:.0f} %)"
    )
    for kind in sorted(totals):
        print(
            f"    {kind:<8}: {hits[kind]}/{totals[kind]} ({100 * hits[kind] / totals[kind]:.0f} %)"
        )
    print(
        f"  clean rewritten (false positives): {rewritten}/{len(clean)} ({100 * rewritten / len(clean):.0f} %)"
    )


if __name__ == "__main__":
    main()
