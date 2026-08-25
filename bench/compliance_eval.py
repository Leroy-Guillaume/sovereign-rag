"""Ground-truth eval of the compliance auditor.

A fully synthetic setting where the truth is known by construction: a
six-article regulation, and internal policies that deliberately cover
articles 1, 2 and 4 while saying nothing about 3, 5 and 6. The audit runs
through the real API (real graph, real local LLM); scoring compares each
verdict to the expected one. Reported: verdict accuracy, gap recall (a
missed gap is the costly error for a RSSI) and compliant precision (a
false "compliant" is the dangerous one).

Environment:
  SOVEREIGN_RAG_URL      target stack (default http://localhost:8070)
  SOVEREIGN_RAG_API_KEY  bearer key (default sk-demo-admin)

Usage: uv run bench/compliance_eval.py
"""

import json
import os
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _tracking import track

BASE = os.environ.get("SOVEREIGN_RAG_URL", "http://localhost:8070")
KEY = os.environ.get("SOVEREIGN_RAG_API_KEY", "sk-demo-admin")

REGULATION = """\
Reglement synthetique sur la protection des donnees

Article 1 - Securite du traitement
Le responsable du traitement met en oeuvre des mesures techniques et
organisationnelles garantissant une securite adaptee au risque.

Article 2 - Notification des violations
Toute violation de la securite des donnees est notifiee a l'autorite de
controle dans un delai de 72 heures.

Article 3 - Delegue a la protection des donnees
Un delegue a la protection des donnees est designe et ses coordonnees
sont publiees.

Article 4 - Registre des traitements
Un registre ecrit de toutes les activites de traitement est tenu et
maintenu a jour.

Article 5 - Analyse d'impact
Une analyse d'impact est conduite avant tout traitement susceptible
d'engendrer un risque eleve.

Article 6 - Transferts internationaux
Tout transfert de donnees hors du pays est encadre par des garanties
appropriees documentees.
"""

POLICY_COVERED = """\
Politique interne de securite de l'information

Chiffrement et controle d'acces: toutes les donnees sont chiffrees au
repos et en transit; l'acces est limite par role et journalise. Des tests
d'intrusion annuels valident que les mesures techniques et
organisationnelles restent adaptees au risque.

Procedure d'incident: toute violation de la securite des donnees est
qualifiee par l'equipe securite puis notifiee a l'autorite de controle
sous 72 heures, avec un rapport d'incident archive.

Registre: un registre des activites de traitement est tenu dans l'outil
GRC et revu trimestriellement par le responsable de la conformite.
"""

POLICY_NOISE = """\
Charte du teletravail

Le collaborateur en teletravail dispose d'un ecran fourni par
l'entreprise et d'un acces VPN. Les reunions d'equipe se tiennent le
mardi. Les frais d'internet sont rembourses a hauteur de 50 pour cent.
"""

# Ground truth by article number: covered by POLICY_COVERED or not.
EXPECTED = {
    "1": "compliant",
    "2": "compliant",
    "3": "gap",
    "4": "compliant",
    "5": "gap",
    "6": "gap",
}


def call(
    method: str, path: str, payload: dict | None = None, raw: bytes | None = None, name: str = ""
) -> dict:
    headers: dict[str, str] = {"Authorization": f"Bearer {KEY}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    if raw is not None:
        boundary = "benchboundary"
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        data = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{name}"\r\nContent-Type: text/plain\r\n\r\n'
            ).encode()
            + raw
            + f"\r\n--{boundary}--\r\n".encode()
        )
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def main() -> None:
    for name, content in [
        ("reglement-synthetique.txt", REGULATION),
        ("politique-securite.txt", POLICY_COVERED),
        ("charte-teletravail.txt", POLICY_NOISE),
    ]:
        call("POST", "/api/documents", raw=content.encode(), name=name)
    for _ in range(120):
        docs = call("GET", "/api/documents")
        if all(d["status"] == "ready" for d in docs):
            break
        time.sleep(1)
    regulation = next(d for d in docs if d["filename"] == "reglement-synthetique.txt")

    t0 = time.time()
    audit = call("POST", "/api/audits", payload={"regulation_id": regulation["id"]})
    for _ in range(360):
        detail = call("GET", f"/api/audits/{audit['id']}")
        if detail["status"] in ("completed", "failed"):
            break
        time.sleep(5)
    elapsed = time.time() - t0
    assert detail["status"] == "completed", detail.get("error")

    scored = 0
    correct = 0
    gap_hits, gap_total = 0, 0
    compliant_claims, compliant_true = 0, 0
    for finding in detail["findings"]:
        article = next((n for n in EXPECTED if n in finding["ref"]), None)
        if article is None:
            continue
        expected = EXPECTED[article]
        scored += 1
        if finding["verdict"] == expected:
            correct += 1
        if expected == "gap":
            gap_total += 1
            if finding["verdict"] == "gap":
                gap_hits += 1
        if finding["verdict"] == "compliant":
            compliant_claims += 1
            if expected == "compliant":
                compliant_true += 1
        print(f"  {finding['ref']:<12} attendu={expected:<10} obtenu={finding['verdict']}")

    print("===== compliance auditor =====")
    print(f"  requirements mapped : {detail['requirements_total']} (6 articles injected)")
    print(f"  verdicts scored     : {scored}")
    print(f"  accuracy            : {correct}/{scored}")
    print(f"  gap recall          : {gap_hits}/{gap_total}")
    print(f"  compliant precision : {compliant_true}/{max(compliant_claims, 1)}")
    print(f"  elapsed             : {elapsed:.0f} s")
    track(
        "compliance",
        "synthetic-6-articles",
        {"regulation": "synthetic", "articles": 6},
        {
            "accuracy": correct / scored if scored else 0.0,
            "gap_recall": gap_hits / gap_total if gap_total else 0.0,
            "compliant_precision": compliant_true / compliant_claims if compliant_claims else 0.0,
            "requirements_mapped": detail["requirements_total"],
            "elapsed_s": elapsed,
        },
    )


if __name__ == "__main__":
    main()
