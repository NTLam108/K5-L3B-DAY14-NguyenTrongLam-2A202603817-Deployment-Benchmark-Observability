"""
Rate limiting (tiêu chí 7) — sliding window 60 giây trên Redis sorted set.

Mỗi API key có một sorted set  ratelimit:<sha256(key)[:16]>:
  member = id duy nhất của request, score = thời điểm (giây, float)

Mỗi request:
  1. ZREMRANGEBYSCORE  xoá các request cũ hơn 60 giây
  2. ZCARD             đếm số request còn trong cửa sổ
  3. Nếu đã đủ RATE_LIMIT_PER_MINUTE → 429 + Retry-After
  4. ZADD + EXPIRE     ghi nhận request này

State nằm trong Redis nên mọi worker/instance dùng chung và vẫn còn sau khi restart.
"""
import hashlib
import math
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _bucket(key: str) -> str:
    # Không lưu API key thô trong Redis
    return "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def check_rate_limit(key: str) -> dict:
    limit = settings.rate_limit_per_minute
    bucket = _bucket(key)
    now = time.time()

    pipe = r.pipeline()
    pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
    pipe.zcard(bucket)
    pipe.zrange(bucket, 0, 0, withscores=True)  # request cũ nhất trong cửa sổ
    _, count, oldest = pipe.execute()

    if count >= limit:
        oldest_ts = oldest[0][1] if oldest else now
        retry_after = max(1, math.ceil(oldest_ts + WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit": limit,
                    "window_seconds": WINDOW_SECONDS, "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after),
                     "X-RateLimit-Limit": str(limit),
                     "X-RateLimit-Remaining": "0"},
        )

    pipe = r.pipeline()
    pipe.zadd(bucket, {f"{now:.6f}-{uuid.uuid4().hex[:8]}": now})
    pipe.expire(bucket, WINDOW_SECONDS + 5)
    pipe.execute()
    return {"limit": limit, "remaining": limit - count - 1}
