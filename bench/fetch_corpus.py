# /// script
# requires-python = ">=3.11"
# dependencies = ["beautifulsoup4", "httpx", "lxml"]
# ///
"""Build the evaluation corpus: EU legal texts from EUR-Lex, in FR/DE/EN, as markdown.

Reuse of EUR-Lex content is authorised under Commission Decision 2011/833/EU
with source acknowledgement; every generated file records its source URL.
A file already present and above 20 KB is kept, so a re-run only fills gaps.

Usage: uv run bench/fetch_corpus.py
"""

import pathlib
import re
import warnings

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

OUT = pathlib.Path(__file__).parent / "corpus"

EURLEX = [  # (celex, slug, title)
    ("32016R0679", "rgpd", "Reglement general sur la protection des donnees"),
    ("32022L2555", "nis2", "Directive NIS2"),
    ("32024R1689", "ai-act", "Reglement sur l'intelligence artificielle"),
    ("32019R0881", "cybersecurity-act", "Cybersecurity Act"),
    ("32022R2065", "dsa", "Digital Services Act"),
    ("32022R1925", "dma", "Digital Markets Act"),
    ("32023R2854", "data-act", "Data Act"),
    ("32022R2554", "dora", "DORA resilience operationnelle numerique"),
    ("32014R0910", "eidas", "Reglement eIDAS"),
    ("32018R1725", "edps", "Protection des donnees par les institutions de l'Union"),
]


def clean(soup):
    for t in soup(["script", "style", "nav", "header", "footer"]):
        t.decompose()
    lines, seen = [], set()
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "div", "td"]):
        if el.find(["p", "div", "h1", "h2", "h3", "h4", "td"]):
            continue
        txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if len(txt) < 3 or txt in seen:
            continue
        seen.add(txt)
        if el.name.startswith("h") or re.match(
            r"^(Art(icle)?\.?\s*\d+|Artikel\s*\d+|Chapitre|Kapitel|Chapter"
            r"|Section|Abschnitt|TITRE|TITEL|TITLE)\b",
            txt,
            re.I,
        ):
            lines.append(f"\n## {txt}\n")
        else:
            lines.append(txt)
    return "\n\n".join(lines)


def grab(url, dest, title, source):
    if dest.exists() and dest.stat().st_size > 20000:
        print(f"  = {dest.name} already present ({dest.stat().st_size // 1024} KB)")
        return
    try:
        r = httpx.get(
            url,
            follow_redirects=True,
            timeout=90,
            headers={"User-Agent": "Mozilla/5.0 (research corpus builder)"},
        )
        r.raise_for_status()
        body = clean(BeautifulSoup(r.text, "lxml"))
        if len(body) < 5000:
            print(f"  ! {dest.name} too short ({len(body)} chars), skipped")
            return
        # Header kept identical to the committed corpus so a re-run reproduces it.
        dest.write_text(
            f"# {title}\n\n> Source: {source}\n> Texte officiel, reutilisation libre\n\n{body}\n",
            encoding="utf-8",
        )
        print(f"  + {dest.name}  {len(body) // 1024} KB")
    except Exception as e:
        print(f"  ! {dest.name}: {type(e).__name__}: {str(e)[:70]}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("== EUR-Lex (EU law) ==")
    for celex, slug, title in EURLEX:
        for lang in ("FR", "DE", "EN"):
            u = f"https://eur-lex.europa.eu/legal-content/{lang}/TXT/HTML/?uri=CELEX:{celex}"
            grab(u, OUT / f"eu-{slug}.{lang.lower()}.md", f"{title} ({lang})", u)
    files = list(OUT.glob("*.md"))
    tot = sum(f.stat().st_size for f in files)
    print(f"\n{len(files)} files, {tot / 1e6:.1f} MB total")


if __name__ == "__main__":
    main()
