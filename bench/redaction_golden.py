"""Build the redaction golden set: synthetic PII injected into real corpus sentences.

Deterministic (fixed seed): the committed redaction_golden.json is exactly
reproducible. Two populations per language:
  - cases: a corpus sentence with 1-3 injected identifiers, each recorded as
    ground truth (type + exact value), used to measure RECALL per type;
  - clean: untouched corpus sentences, used to measure FALSE POSITIVES (an
    engine that rewrites clean legal text destroys the very passages the
    product exists to cite verbatim).

Usage: uv run bench/redaction_golden.py   (writes bench/redaction_golden.json)
"""

import json
import pathlib
import random
import re

HERE = pathlib.Path(__file__).parent
SEED = 42
CASES_PER_LANG = 80
CLEAN_PER_LANG = 40

FIRST = {
    "fr": ["Jean", "Marie", "Luc", "Sophie", "Pierre", "Camille", "Hugo", "Elise"],
    "de": ["Hans", "Anna", "Peter", "Ursula", "Stefan", "Heidi", "Markus", "Verena"],
    "en": ["John", "Mary", "James", "Susan", "David", "Karen", "Peter", "Laura"],
}
LAST = {
    "fr": ["Dupont", "Favre", "Martin", "Rochat", "Bonvin", "Perret"],
    "de": ["Mueller", "Keller", "Schmid", "Baumann", "Frei", "Huber"],
    "en": ["Smith", "Brown", "Taylor", "Wilson", "Clark", "Walker"],
}
DOMAINS = ["example.ch", "bluewin.ch", "gmx.de", "example.org", "mail.com"]
STREETS = {
    "fr": ["Rue du Rhone 12, 1204 Geneve", "Avenue de la Gare 3, 1003 Lausanne"],
    "de": ["Bahnhofstrasse 5, 8001 Zuerich", "Marktgasse 21, 3011 Bern"],
    "en": ["12 Station Road, 1204 Geneva", "5 Market Street, 3011 Bern"],
}
ORGS = {
    "fr": ["Fiduciaire Leman SA", "Cabinet Vaudois Conseil"],
    "de": ["Treuhand Alpina AG", "Kanzlei Rheintal GmbH"],
    "en": ["Lakeside Advisory Ltd", "Alpine Trust Services"],
}
# Injection templates: {s} is the corpus sentence, other slots are PII.
TEMPLATES = {
    "fr": [
        ("{s} Pour toute question, contactez {name} ({email}).", ["name", "email"]),
        ("{s} Le prepose {name} est joignable au {phone}.", ["name", "phone"]),
        ("{s} Paiement sur le compte {iban} de {org}.", ["iban", "org"]),
        ("{s} Dossier de {name}, n. AVS {avs}.", ["name", "avs"]),
        ("{s} Adresse de notification : {name}, {address}.", ["name", "address"]),
        ("{s} Reference : {email}, tel. {phone}.", ["email", "phone"]),
    ],
    "de": [
        ("{s} Bei Fragen wenden Sie sich an {name} ({email}).", ["name", "email"]),
        ("{s} Der Berater {name} ist unter {phone} erreichbar.", ["name", "phone"]),
        ("{s} Zahlung auf das Konto {iban} der {org}.", ["iban", "org"]),
        ("{s} Dossier von {name}, AHV-Nr. {avs}.", ["name", "avs"]),
        ("{s} Zustelladresse: {name}, {address}.", ["name", "address"]),
        ("{s} Kontakt: {email}, Tel. {phone}.", ["email", "phone"]),
    ],
    "en": [
        ("{s} For questions contact {name} ({email}).", ["name", "email"]),
        ("{s} The officer {name} can be reached at {phone}.", ["name", "phone"]),
        ("{s} Payment to account {iban} held by {org}.", ["iban", "org"]),
        ("{s} File of {name}, AVS no. {avs}.", ["name", "avs"]),
        ("{s} Notification address: {name}, {address}.", ["name", "address"]),
        ("{s} Reference: {email}, phone {phone}.", ["email", "phone"]),
    ],
}

_SENTENCE = re.compile(r"(?<=[.;])\s+")


def corpus_sentences(lang: str, rng: random.Random, count: int) -> list[str]:
    pool: list[str] = []
    for path in sorted(HERE.glob(f"corpus/*.{lang}.md")):
        for raw in _SENTENCE.split(path.read_text(encoding="utf-8")):
            sentence = " ".join(raw.split())
            if 80 <= len(sentence) <= 220 and not sentence.startswith(("#", "|", "[")):
                pool.append(sentence)
    rng.shuffle(pool)
    return pool[:count]


def make_pii(lang: str, rng: random.Random) -> dict[str, str]:
    name = f"{rng.choice(FIRST[lang])} {rng.choice(LAST[lang])}"
    email = f"{name.split()[0].lower()}.{name.split()[1].lower()}@{rng.choice(DOMAINS)}"
    phone = rng.choice(
        [
            f"+41 79 {rng.randint(100, 999)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
            f"022 {rng.randint(100, 999)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
            f"+33 6 {rng.randint(10, 99)} {rng.randint(10, 99)} "
            f"{rng.randint(10, 99)} {rng.randint(10, 99)}",
            f"+49 30 {rng.randint(1000000, 9999999)}",
        ]
    )
    iban = (
        f"CH{rng.randint(10, 99)} {rng.randint(1000, 9999)} {rng.randint(1000, 9999)} "
        f"{rng.randint(1000, 9999)} {rng.randint(1000, 9999)} {rng.randint(10, 99)}"
    )
    avs = f"756.{rng.randint(1000, 9999)}.{rng.randint(1000, 9999)}.{rng.randint(10, 99)}"
    return {
        "name": name,
        "email": email,
        "phone": phone,
        "iban": iban,
        "avs": avs,
        "address": rng.choice(STREETS[lang]),
        "org": rng.choice(ORGS[lang]),
    }


def main() -> None:
    rng = random.Random(SEED)
    cases: list[dict[str, object]] = []
    clean: list[dict[str, str]] = []
    for lang in ("fr", "de", "en"):
        sentences = corpus_sentences(lang, rng, CASES_PER_LANG + CLEAN_PER_LANG)
        for i in range(CASES_PER_LANG):
            template, slots = TEMPLATES[lang][i % len(TEMPLATES[lang])]
            pii = make_pii(lang, rng)
            text = template.format(s=sentences[i], **pii)
            cases.append(
                {
                    "id": f"{lang}-{i:03d}",
                    "lang": lang,
                    "text": text,
                    "entities": [{"type": slot, "value": pii[slot]} for slot in slots],
                }
            )
        for i, sentence in enumerate(sentences[CASES_PER_LANG:]):
            clean.append({"id": f"{lang}-clean-{i:03d}", "lang": lang, "text": sentence})
    out = HERE / "redaction_golden.json"
    out.write_text(
        json.dumps({"cases": cases, "clean": clean}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"{len(cases)} cases, {len(clean)} clean -> {out.name}")


if __name__ == "__main__":
    main()
