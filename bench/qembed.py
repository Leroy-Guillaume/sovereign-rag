"""Query-embedding cache shared by the SQL-direct scripts.

Those scripts (sweep, compare, rerank_eval, reranker_ladder) bypass the API,
so they must embed questions with the same model that embedded the chunks in
the database. The default is the model the recorded results used; set
BENCH_EMBED_MODEL to the stack's EMBEDDING_MODEL when they differ. The
asymmetric-prefix rule mirrors the backend's embeddings adapter: e5-family
models get "query: " prepended, others nothing.

Embeddings are cached under bench/.cache/, keyed by model, so repeated runs
do not pay the encoding cost again.

Environment:
  BENCH_EMBED_MODEL   sentence-transformers model id (default BAAI/bge-m3)
  BENCH_EMBED_DEVICE  torch device (default: library auto-detection)
"""

import json
import os
import pathlib

MODEL = os.environ.get("BENCH_EMBED_MODEL", "BAAI/bge-m3")
DEVICE = os.environ.get("BENCH_EMBED_DEVICE") or None
CACHE = pathlib.Path(__file__).parent / ".cache" / f"qembs-{MODEL.replace('/', '--')}.json"


def load_qembs(questions):
    """Return {question: embedding}, encoding whatever the cache does not cover."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    missing = [q for q in questions if q not in cache]
    if missing:
        from sentence_transformers import SentenceTransformer

        print(f"embedding {len(missing)} questions with {MODEL}...", flush=True)
        prefix = "query: " if "e5" in MODEL.lower() else ""
        model = SentenceTransformer(MODEL, device=DEVICE)
        vecs = model.encode([prefix + q for q in missing], normalize_embeddings=True, batch_size=16)
        cache.update({q: v.tolist() for q, v in zip(missing, vecs, strict=True)})
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    return cache


def as_pgvector(emb):
    return "[" + ",".join(f"{x:.7f}" for x in emb) + "]"
