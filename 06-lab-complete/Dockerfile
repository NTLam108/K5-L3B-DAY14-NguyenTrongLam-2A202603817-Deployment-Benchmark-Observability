# ============================================================
# Production Dockerfile — multi-stage
#
#   builder : cài dependencies vào virtualenv /opt/venv
#   runtime : python:3.11-slim sạch, chỉ copy /opt/venv + code, chạy bằng user non-root
#
# Mọi package trong requirements.txt đều có wheel dựng sẵn cho linux/amd64,
# nên không cần cài gcc ở builder (build nhanh hơn nhiều).
# ============================================================

# ── Stage 1: builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements trước để layer pip install được cache khi chỉ sửa code
COPY requirements.txt .
RUN pip install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

RUN groupadd --system app && useradd --system --gid app --home-dir /app --no-create-home app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app/ ./app/
COPY --chown=app:app utils/ ./utils/

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8000'), timeout=3)" || exit 1

# `exec` để uvicorn thay thế shell và là PID 1 → nhận SIGTERM trực tiếp khi `docker stop`.
# ${PORT:-8000}: Railway/Render cấp PORT qua biến môi trường.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
