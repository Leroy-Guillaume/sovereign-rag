"""Deep-search orchestration (LangGraph runtime, our clients inside the nodes).

LangGraph is used strictly as a graph runtime: routing, bounded cycles and
state. Every model call goes through the project's LLMClient (so the PII
boundary and provider seams apply unchanged) and every retrieval goes
through the project's VectorStore with the caller's ACL. LangSmith
telemetry is never enabled: no tracing env vars are set and none should be
(documented in .env.example); nothing leaves the machine.
"""
