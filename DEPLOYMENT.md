# Deployment Information

## Public URL

https://agent-production-ffd58773.up.railway.app

## Platform

**Railway** — deploy thư mục `06-lab-complete/` (agent Part 6) bằng Railway CLI (`railway up`).

Project Railway gồm 2 service:

| Service | Nguồn | Vai trò |
|---------|-------|---------|
| `agent` | Build từ `06-lab-complete/Dockerfile` theo `06-lab-complete/railway.toml` (`builder = "DOCKERFILE"`, `healthcheckPath = "/health"`) | FastAPI agent, uvicorn 2 worker, lắng nghe theo biến `PORT` do Railway cấp |
| `Redis` | Railway Redis (`railway add -d redis`) | State dùng chung: rate limit (sorted set) và chi phí theo ngày |

Agent nối tới Redis qua mạng nội bộ của Railway, bằng biến tham chiếu `REDIS_URL=${{Redis.REDIS_URL}}`.

## Test Commands

```bash
BASE=https://agent-production-ffd58773.up.railway.app
# AGENT_API_KEY: key đã đặt trên Railway (không ghi trong repo)
```

### Health check

```bash
curl $BASE/health
# {"status":"ok","uptime_seconds":515.7,"environment":"production"}

curl $BASE/ready
# {"ready":true}          ← Redis trên Railway kết nối được
```

### API test (with authentication)

```bash
# Không có key → 401
curl -X POST $BASE/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
# {"detail":"Missing or invalid API key. Include header: X-API-Key: <your-key>"}

# Có key → 200
curl -X POST $BASE/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

### Self-test (4 lệnh của CP6, chỉ in mã HTTP)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả: `200 · 200 · 401 · 200` (ảnh `screenshots/test.png`).

Kiểm tra thêm bằng script chấm:

```text
$ python check_production_ready.py --public-url https://agent-production-ffd58773.up.railway.app
     ✅ Public URL: GET https://agent-production-ffd58773.up.railway.app/health → 200
```

## Environment Variables Set

Đặt trên Railway (service `agent` → Variables) bằng `railway variable set`, **không** ghi trong code hay trong repo:

| Biến | Giá trị / nguồn |
|------|-----------------|
| `AGENT_API_KEY` | Key ngẫu nhiên 32 byte (`secrets.token_urlsafe(32)`), đặt qua `--stdin` |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` — biến tham chiếu tới service Redis |
| `ENVIRONMENT` | `production` (tắt `/docs`) |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `LOG_LEVEL` | `INFO` |
| `PORT` | Railway tự cấp; `CMD` trong Dockerfile đọc `${PORT:-8000}` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
