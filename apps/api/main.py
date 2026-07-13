"""API entrypoint. Run:
.venv\\Scripts\\python.exe -m uvicorn main:app --app-dir apps/api --host 127.0.0.1 --port 8200
"""

from autopilot.api.app import app

__all__ = ["app"]
