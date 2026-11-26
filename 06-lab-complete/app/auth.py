"""
API Key authentication (tiêu chí 6).

  • Client gửi header  X-API-Key: <key>
  • Key phải trùng biến môi trường AGENT_API_KEY
  • Thiếu hoặc sai key → HTTP 401 (không phải 403 hay 422)
"""
import hmac

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

# auto_error=False: thiếu header thì nhận None rồi tự trả 401.
# Nếu để mặc định (auto_error=True), FastAPI trả 403 khi thiếu header.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho /ask. Trả về API key hợp lệ (dùng làm khoá rate limit)."""
    expected = settings.agent_api_key
    # expected rỗng = chưa cấu hình AGENT_API_KEY → từ chối hết (fail closed)
    if not api_key or not expected or not hmac.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API key. Include header: X-API-Key: <your-key>",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
