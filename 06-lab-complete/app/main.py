"""
Production AI Agent — Part 6 Final Project.

Chạy:   uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
Kiểm tra: python check_production_ready.py

Luồng của POST /ask:
  verify_api_key (401) → check_rate_limit (429) → check_budget (402) → LLM → record_cost
"""
import time
import uuid
from contextlib import asynccontextmanager

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.logging_config import setup_logging
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask

logger = setup_logging(settings.log_level)

START_TIME = time.time()
_state = {"ready": False}


# ─────────────────────────────────────────────────────────
# Lifecycle — startup / graceful shutdown (tiêu chí 11)
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Không bắt buộc Redis lúc khởi động: container vẫn lên được, /ready báo 503 tới khi Redis có.
    logger.info("startup", extra={"event": "startup", "environment": settings.environment,
                                  "port": settings.port, "redis_ok": redis_healthy(),
                                  "api_key_configured": bool(settings.agent_api_key)})
    _state["ready"] = True
    yield
    # Tới đây uvicorn đã nhận SIGTERM, ngừng nhận kết nối mới và chờ xong các request đang chạy.
    _state["ready"] = False
    logger.info("shutdown", extra={"event": "shutdown",
                                   "uptime_s": round(time.time() - START_TIME, 1)})
    try:
        r.close()
    except Exception:
        pass


app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan,
              docs_url=None if settings.environment == "production" else "/docs")


# ─────────────────────────────────────────────────────────
# Middleware — log JSON cho mỗi request (tiêu chí 10)
# ─────────────────────────────────────────────────────────
@app.middleware("http")
async def access_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        if request.url.path not in ("/health", "/ready"):  # probe gọi liên tục, không cần log
            logger.info("request", extra={
                "event": "request", "request_id": request_id, "method": request.method,
                "path": request.url.path, "status": status,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            })


# ─────────────────────────────────────────────────────────
# Xử lý lỗi — mã lỗi rõ ràng, không lộ stack trace ra client
# ─────────────────────────────────────────────────────────
@app.exception_handler(redis.RedisError)
async def redis_error_handler(request: Request, exc: redis.RedisError):
    logger.error("redis_error", extra={"event": "redis_error", "path": request.url.path,
                                       "error": type(exc).__name__})
    return JSONResponse(status_code=503,
                        content={"detail": "Service temporarily unavailable (state store)"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.error("unhandled_error", exc_info=exc,
                 extra={"event": "unhandled_error", "path": request.url.path})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ─────────────────────────────────────────────────────────
# Health / readiness (tiêu chí 4, 5)
# ─────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Liveness: process còn chạy là 200 — KHÔNG phụ thuộc Redis (tránh restart storm)."""
    return {"status": "ok", "uptime_seconds": round(time.time() - START_TIME, 1),
            "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: chỉ nhận traffic khi đã khởi động xong, chưa shutdown và Redis kết nối được."""
    if not _state["ready"]:
        raise HTTPException(status_code=503, detail="Agent is starting up or shutting down")
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not available")
    return {"ready": True}


# ─────────────────────────────────────────────────────────
# Agent endpoint
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    # `def` (không async): FastAPI chạy trong threadpool, mock LLM có time.sleep
    # nên không chặn event loop — /health vẫn trả lời ngay trong lúc LLM đang chạy.
    rate = check_rate_limit(api_key)   # 429
    check_budget()                     # 402

    answer = llm_ask(body.question)

    cost = record_cost(estimate_tokens(body.question), estimate_tokens(answer))
    return {
        "question": body.question,
        "answer": answer,
        "usage": {"cost_usd": round(cost, 8), "requests_remaining": rate["remaining"]},
    }
