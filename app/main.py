"""FastAPI app assembly: lifespan, middleware, static files, routes."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import ALLOWED_HOSTS, STATIC_DIR
from app.downloads import cleanup_loop
from app.routes import router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # keep a reference so the task can't be garbage-collected mid-flight
    cleanup = asyncio.create_task(cleanup_loop())
    yield
    cleanup.cancel()


app = FastAPI(title="yt-dlp Web GUI", lifespan=lifespan)

# no CORS middleware on purpose: the frontend is served from this same origin,
# so cross-origin pages get no permission to drive the (unauthenticated) API

# optional Host-header allowlist (DNS-rebinding protection)
if ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(router)
