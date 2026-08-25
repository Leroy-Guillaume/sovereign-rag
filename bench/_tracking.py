"""Optional MLflow experiment tracking for the bench harness.

Sovereignty stance: tracking is bench-only instrumentation (backend/src never
imports it), fully optional, and local by default. When mlflow is installed
(uv sync --group tracking from backend/), runs are recorded to a plain file
store under ~/AI/runs/sovereign-rag-mlflow; nothing leaves the machine. When
mlflow is absent (the default environment, CI, or the PEP 723 script env of
redaction_eval.py), track() is a silent no-op, so every bench script keeps
working unchanged.

Set MLFLOW_TRACKING_URI to point somewhere else (another directory, or a
self-hosted server) when you explicitly want to.
"""

import os
import pathlib

DEFAULT_STORE = pathlib.Path("~/AI/runs/sovereign-rag-mlflow")


def track(experiment: str, run_name: str, params: dict, metrics: dict) -> None:
    """Record one bench run; never raises, no-op without mlflow installed."""
    try:
        import mlflow
    except ImportError:
        return
    try:
        uri = os.environ.get("MLFLOW_TRACKING_URI")
        if not uri:
            store = DEFAULT_STORE.expanduser()
            store.mkdir(parents=True, exist_ok=True)
            uri = f"file:{store}"
            # MLflow >= 3.15 keeps the plain-file backend behind an opt-in.
            # It is exactly what we want here: local files, no server, no db.
            os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(experiment)
        with mlflow.start_run(run_name=run_name):
            mlflow.log_params(params)
            mlflow.log_metrics(metrics)
    except Exception as exc:
        print(f"  [tracking] mlflow logging skipped: {exc}")
