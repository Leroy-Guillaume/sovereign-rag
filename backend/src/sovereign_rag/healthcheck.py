"""Local HTTP liveness probe for the Docker HEALTHCHECK.

The runtime image ships no curl/wget; ``python -m sovereign_rag.healthcheck``
performs the probe with httpx (already a core dependency). Exit code 0 when
the API answers 200 on /healthz, 1 otherwise.
"""

import os
import sys

import httpx


def main() -> int:
    port = os.environ.get("PORT", "8000")
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=3)
    except httpx.HTTPError:
        return 1
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
