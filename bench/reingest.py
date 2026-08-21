"""Upload the bench corpus, one document at a time, waiting for each to index.

Sequential on purpose: local CPU embedding thrashes under concurrent
ingestion (measured: 30 concurrent uploads completed nothing in 25 minutes,
while one at a time the largest document went through in 111 s).

Nothing is deleted here; re-uploading an already-ingested file is handled by
the API's deduplication.

Environment:
  SOVEREIGN_RAG_URL      target stack (default http://localhost:8000)
  SOVEREIGN_RAG_API_KEY  bearer key (default sk-demo-admin)

Usage: uv run bench/reingest.py
"""

import json
import os
import pathlib
import subprocess
import time

BASE_URL = os.environ.get("SOVEREIGN_RAG_URL", "http://localhost:8000")
API_KEY = os.environ.get("SOVEREIGN_RAG_API_KEY", "sk-demo-admin")
CORPUS = pathlib.Path(__file__).parent / "corpus"


def list_documents():
    out = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {API_KEY}", f"{BASE_URL}/api/documents"],
        capture_output=True,
        text=True,
    ).stdout
    rows = json.loads(out)
    return rows if isinstance(rows, list) else rows.get("items", [])


def main():
    files = sorted(CORPUS.glob("*.md"))
    print(f"{len(files)} files", flush=True)
    t00 = time.time()
    for i, f in enumerate(files, 1):
        r = subprocess.run(
            [
                "curl",
                "-s",
                "-X",
                "POST",
                f"{BASE_URL}/api/documents",
                "-H",
                f"Authorization: Bearer {API_KEY}",
                "-F",
                f"file=@{f};type=text/markdown",
            ],
            capture_output=True,
            text=True,
        ).stdout
        try:
            doc_id = json.loads(r)["id"]
        except (ValueError, KeyError):
            print(f"  [{i:>2}/{len(files)}] {f.name:<30} upload failed: {r[:80]}", flush=True)
            continue
        t0 = time.time()
        while True:
            time.sleep(5)
            st = next((d["status"] for d in list_documents() if d["id"] == doc_id), "?")
            if st != "processing":
                break
        print(f"  [{i:>2}/{len(files)}] {f.name:<30} {st}  {time.time() - t0:5.0f}s", flush=True)
    print(f"TOTAL {time.time() - t00:.0f}s", flush=True)


if __name__ == "__main__":
    main()
