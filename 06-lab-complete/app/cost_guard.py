"""
Cost guard (tiêu chí 8).

  • Tổng chi phí LLM trong ngày (UTC) lưu ở Redis key  cost:daily:<YYYY-MM-DD>
  • check_budget(): tổng ≥ DAILY_BUDGET_USD → HTTP 402 (gọi TRƯỚC khi gọi LLM)
  • record_cost():  cộng chi phí của request bằng INCRBYFLOAT (atomic) (gọi SAU khi gọi LLM)
  • Key có tên theo ngày nên tự "reset" khi sang ngày mới; EXPIRE 2 ngày để Redis tự dọn.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

KEY_TTL_SECONDS = 2 * 24 * 3600


def _daily_key() -> str:
    return "cost:daily:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def spent_today() -> float:
    return float(r.get(_daily_key()) or 0.0)


def check_budget() -> None:
    """Hết budget → raise HTTPException(402)."""
    spent = spent_today()
    budget = settings.daily_budget_usd
    if spent >= budget:
        raise HTTPException(
            status_code=402,
            detail={"error": "Daily budget exceeded", "spent_usd": round(spent, 6),
                    "budget_usd": budget, "resets_at": "00:00 UTC"},
        )


def estimate_tokens(text: str) -> int:
    # Ước lượng thô ~4 ký tự / token; mock LLM không trả usage thật
    return max(1, len(text) // 4)


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Cộng chi phí request vào tổng của ngày, trả về chi phí của request."""
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    key = _daily_key()
    pipe = r.pipeline()
    pipe.incrbyfloat(key, cost)
    pipe.expire(key, KEY_TTL_SECONDS)
    pipe.execute()
    return cost
