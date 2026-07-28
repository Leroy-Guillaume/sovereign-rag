"""Shared pytest configuration.

psycopg's async connections cannot run on Windows' default ProactorEventLoop;
force the selector-based policy so the async integration tests work on win32.
"""

import asyncio
import sys

if sys.platform == "win32":
    # The policy API is deprecated from Python 3.14; this project pins 3.12.
    policy = asyncio.WindowsSelectorEventLoopPolicy()
    asyncio.set_event_loop_policy(policy)  # pyright: ignore[reportDeprecated]
