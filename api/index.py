import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from backend.main import app
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class StripApiPrefix(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            request.scope["path"] = request.url.path[4:]  # strip /api
        elif request.url.path == "/api":
            request.scope["path"] = "/"
        return await call_next(request)

app.add_middleware(StripApiPrefix)
