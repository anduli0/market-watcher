"""LLM layer — headless Claude (operator subscription) invoked BY the web server.

No API key, no Claude Code session: the FastAPI process shells out to `claude -p`
so the analysis runs on the website itself (auto cadence + dashboard button).
Everything degrades gracefully to the deterministic pipeline when auth is absent.
"""
