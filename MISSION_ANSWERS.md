# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

File: `01-localhost-vs-production/develop/app.py`

1. **Secret hardcode trong code** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-..."` và `DATABASE_URL = "postgresql://admin:password123@..."`. Push lên GitHub là lộ key và mật khẩu DB; muốn đổi key phải sửa code và deploy lại.
2. **Log ra secret** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Khi chạy thử, key thật sự xuất hiện trong log server (xem Exercise 1.2). Ai đọc được log là có key.
3. **Dùng `print()` thay vì logging có cấu trúc** (dòng 33, 38): không có level, không có timestamp, không phải JSON nên log aggregator (Loki, Datadog…) không parse/lọc được. Dòng 38 còn in toàn bộ câu trả lời, dễ lộ dữ liệu người dùng.
4. **Config cứng, không đọc từ env** (dòng 21–22): `DEBUG = True`, `MAX_TOKENS = 500`. Muốn đổi giữa dev/staging/prod phải sửa code.
5. **Không có health check** (dòng 42): gọi `GET /health` trả **404**. Platform (Railway, Render, Docker, Kubernetes) không biết agent còn sống hay đã treo để restart.
6. **Port cố định 8000** (dòng 52): không đọc biến `PORT` mà Railway/Render inject. Thực tế khi làm bài, cổng 8000 trên máy đang bị một container khác chiếm, và vì port hardcode nên không thể đổi bằng env, phải tắt container kia mới chạy được.
7. **Bind `host="localhost"`** (dòng 51): chỉ nhận kết nối từ chính máy đó. Chạy trong container thì từ bên ngoài không gọi vào được; production phải bind `0.0.0.0`.
8. **`reload=True`** (dòng 53): chế độ auto-reload dành cho dev, tốn tài nguyên (theo dõi file) và không nên bật trong production.
9. **Không xử lý shutdown / không có lifecycle**: không có hook startup/shutdown để đóng kết nối, không có readiness probe để load balancer biết khi nào ngừng gửi traffic.
10. **Không validate input**: `question` nhận qua query string, không kiểm tra rỗng hay độ dài.

### Exercise 1.2: Chạy bản develop

Chạy trong WSL2 (Python 3.11.18): `cd 01-localhost-vs-production/develop && pip install -r requirements.txt && python app.py`

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found

{"detail":"Not Found"}
```

Log server, cho thấy reloader của chế độ dev đang chạy và secret bị in ra:

```text
INFO:     Will watch for changes in these directories: ['.../01-localhost-vs-production/develop']
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [1887] using WatchFiles
Starting agent on localhost:8000...
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
INFO:     127.0.0.1:60670 - "POST /ask?question=Hello HTTP/1.1" 200 OK
INFO:     127.0.0.1:60680 - "GET /health HTTP/1.1" 404 Not Found
```

**Quan sát:** agent chạy và trả lời được, nhưng không có health check, log lộ key, chỉ nghe trên `localhost`, bật reloader (`WatchFiles`) và không thể đổi cổng nếu không sửa code. Chạy được chưa có nghĩa là production-ready.

### Exercise 1.3: Chạy bản production

`cd ../production && cp .env.example .env && pip install -r requirements.txt && python app.py` (`.env` đã có trong `.gitignore`):

```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:35:53.037704+00:00"}

$ curl http://localhost:8000/ready
{"ready":true}

$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{}'
HTTP/1.1 422 Unprocessable Entity
```

Log khởi động: `Uvicorn running on http://0.0.0.0:8000` (bind mọi interface, không có reloader). Gửi SIGTERM (`kill -TERM <pid>`), server tắt có thứ tự:

```text
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [1910]
```

### Exercise 1.3: Comparison table

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hardcode trong code (`DEBUG`, `MAX_TOKENS`, key, DB URL) | Đọc từ env qua `config.py` (`Settings` dataclass), có `.env.example` | Một image chạy được ở mọi môi trường chỉ bằng cách đổi env (12-Factor: Config). Đổi cấu hình không cần sửa code và build lại |
| Secrets | Key và mật khẩu DB nằm trong code, còn bị in ra log | Lấy từ env, không log; `validate()` báo lỗi nếu `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` | Secret trong code sẽ nằm mãi trong lịch sử git. Fail fast giúp phát hiện thiếu cấu hình ngay lúc khởi động thay vì lúc có request |
| Host / Port | `localhost:8000` cố định | `HOST` mặc định `0.0.0.0`, `PORT` từ env | Container cần bind `0.0.0.0` để nhận traffic từ ngoài; cloud platform tự chọn và inject `PORT` |
| Health check | Không có (`/health` → 404) | `/health` (liveness: uptime, version) và `/ready` (readiness, 503 khi chưa sẵn sàng) | Platform dùng `/health` để biết khi nào restart container, load balancer dùng `/ready` để biết khi nào gửi traffic vào |
| Logging | `print()`, có in secret | `logging` với format JSON, chỉ log metadata (độ dài câu hỏi, IP), không log secret | Log JSON parse và tìm kiếm được trên log aggregator; không lộ secret hay dữ liệu người dùng |
| Shutdown | Tắt đột ngột, không có cleanup | `lifespan` có phần shutdown (`is_ready = False`, chờ request đang chạy), có handler SIGTERM | Khi deploy hoặc scale down, platform gửi SIGTERM; tắt an toàn giúp request đang xử lý không bị cắt ngang |
| Reload | `reload=True` luôn bật | Chỉ bật khi `DEBUG=true` | Auto-reload tốn tài nguyên và không ổn định trong production |
| Input | Query string, không kiểm tra | JSON body, thiếu `question` → 422 | Trả mã lỗi rõ ràng thay vì xử lý dữ liệu rỗng |
| CORS | Không cấu hình | Chỉ cho phép `ALLOWED_ORIGINS` từ env | Giới hạn website nào được gọi API từ trình duyệt |

### Ghi chú thêm khi chạy thử bản production

- **Log JSON không hiện ra.** Trong log thực tế chỉ thấy dòng `WARNING:root:OPENAI_API_KEY not set — using mock LLM` và log của uvicorn, không thấy các dòng `{"event": "startup", ...}`. Nguyên nhân: `config.py` gọi `logging.warning()` lúc import (trong `validate()`), việc này tự cấu hình root logger với format mặc định và level WARNING trước khi `app.py` gọi `logging.basicConfig(...)`. `basicConfig` không làm gì nếu root logger đã có handler, nên format JSON và level INFO không được áp dụng. Cách sửa: gọi `basicConfig` trước khi import `config`, hoặc thêm `force=True`.
- **`.env` không được nạp.** `requirements.txt` có `python-dotenv` nhưng code không gọi `load_dotenv()`, nên giá trị trong `.env` chỉ có tác dụng nếu được export vào môi trường (vd Docker `env_file`, hoặc `set -a; source .env`). App vẫn chạy được nhờ các giá trị mặc định trong `config.py`.
- **Format log ghép chuỗi JSON thủ công** (`'{"time":"...","msg":"%(message)s"}'`), nên khi `message` đã là JSON hoặc chứa dấu `"`, dòng log sẽ không còn là JSON hợp lệ. Part 6 cần tự viết `JsonFormatter` dùng `json.dumps` để tránh lỗi này.

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

File: `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11`, bản Python đầy đủ trên Debian (có sẵn gcc, header, nhiều thư viện hệ thống). Tiện nhưng rất nặng: image cuối đo được 1.67 GB.
2. **Working directory:** `/app` (`WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` sau đó chạy trong thư mục này; `docker exec` vào container cũng thấy `pwd` = `/app`.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo từng layer, layer nào thay đổi thì mọi layer phía sau phải build lại. Dependencies ít khi đổi, code đổi liên tục. Copy `requirements.txt` rồi `pip install` trước, sau đó mới copy `app.py`, thì khi chỉ sửa code, layer `pip install` vẫn dùng cache và không phải cài lại. Thực tế: build lại image develop khi không đổi gì chỉ mất **2.35 giây** vì mọi layer đều lấy từ cache. Nếu `COPY . .` trước `pip install`, sửa một dòng code cũng làm cài lại toàn bộ dependencies.
4. **`CMD` vs `ENTRYPOINT`:** `CMD` là lệnh/tham số **mặc định**, bị thay thế hoàn toàn nếu truyền lệnh khi chạy (`docker run my-agent:develop python -V` sẽ chạy `python -V` thay cho `python app.py`). `ENTRYPOINT` là chương trình **cố định** của container, tham số của `docker run` được nối thêm vào sau nó (chỉ đổi được bằng `--entrypoint`). Hay dùng kết hợp: `ENTRYPOINT ["python"]` + `CMD ["app.py"]` để có lệnh chính cố định và tham số mặc định đổi được. Cả hai nên viết dạng exec form (JSON array) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và chạy image develop

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d --rm --name cp2-develop -p 8000:8000 my-agent:develop

$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.5,"container":true}
```

Debug container:

```text
$ docker logs cp2-develop
INFO:     Started server process [1]
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:46006 - "POST /ask?question=What%20is%20Docker HTTP/1.1" 200 OK
INFO:     172.17.0.1:46018 - "GET /health HTTP/1.1" 200 OK

$ docker exec cp2-develop sh -c 'whoami; pwd; ls; python --version'
root
/app
__pycache__  app.py  requirements.txt  utils
Python 3.11.18
```

Nhận xét: container develop chạy bằng **root**. Nếu app bị khai thác, kẻ tấn công có quyền root trong container.

### Exercise 2.3: Multi-stage build

File: `02-docker/production/Dockerfile`

- **Stage 1 (`builder`)**, từ `python:3.11-slim`: cài công cụ build (`gcc`, `libpq-dev`), rồi `pip install --user -r requirements.txt` để toàn bộ package nằm gọn trong `/root/.local`. Stage này chỉ dùng để build, không được deploy.
- **Stage 2 (`runtime`)**, từ một `python:3.11-slim` mới, sạch: tạo user `appuser` (non-root), chỉ `COPY --from=builder /root/.local` (layer này nặng **40.8 MB**), copy `main.py` và `utils/mock_llm.py`, `chown` cho `appuser`, chuyển `USER appuser`, thêm `HEALTHCHECK` gọi `/health`, chạy `uvicorn ... --workers 2`.
- **Vì sao nhỏ hơn:**
  1. Base `python:3.11-slim` thay cho `python:3.11` bản đầy đủ: bỏ compiler, header và rất nhiều thư viện hệ thống không cần khi chạy.
  2. `gcc`, `libpq-dev`, cache của apt chỉ nằm trong stage builder và bị bỏ đi; image cuối chỉ lấy đúng phần đã cài xong.
  3. `pip install --no-cache-dir` không để lại cache pip.

### Exercise 2.3: Image size comparison

Đo bằng `docker images my-agent` và `docker image inspect --format '{{.Size}}'`:

```text
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:advanced   d43fcb47db0d        240MB         57.4MB
my-agent:develop    1b235570e1ac       1.67GB          426MB

my-agent:develop  1667788332 bytes
my-agent:advanced  239815271 bytes
```

- Develop: **1,667.8 MB** (1,667,788,332 bytes)
- Production: **239.8 MB** (239,815,271 bytes)
- Difference: production nhỏ hơn **85.6%** (develop lớn gấp ~**6.95** lần). Tính: (1,667,788,332 − 239,815,271) / 1,667,788,332 = 0.856.
- Cột `CONTENT SIZE` (kích thước nén khi push/pull) cũng giảm từ 426 MB xuống 57.4 MB, nghĩa là pull/deploy nhanh hơn nhiều.

Quan sát thêm: bước `apt-get install gcc libpq-dev` ở stage builder mất khoảng **14 phút** trên máy này (mạng tải từ `deb.debian.org` chậm), trong khi `requirements.txt` chỉ có `fastapi` và `uvicorn`, đều có wheel dựng sẵn và không cần biên dịch. Với project này có thể bỏ bước cài `gcc` để build nhanh hơn mà image cuối không đổi.

### Exercise 2.4: Docker Compose stack

Chạy trong `02-docker/production/` (sau `touch .env.local`): `docker compose -p k5-day14-docker up -d --build`

```text
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up 19 seconds (healthy)   8000/tcp
nginx     nginx:alpine            Up 19 seconds             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 29 seconds (healthy)   6333-6334/tcp
redis     redis:7-alpine          Up 29 seconds (healthy)   6379/tcp
```

**Sơ đồ kiến trúc:**

```text
                 Client (curl / browser)
                          │  http://localhost:80
                          ▼
┌──────────────────── network "internal" (bridge) ────────────────────┐
│                                                                      │
│   ┌────────────────────────────┐                                     │
│   │ nginx  (nginx:alpine)      │  reverse proxy + load balancer,     │
│   │ cổng 80/443 mở ra host     │  rate limit 10 req/s/IP, security   │
│   └─────────────┬──────────────┘  headers                            │
│                 │ proxy_pass http://agent:8000                        │
│                 ▼                                                     │
│   ┌────────────────────────────┐                                     │
│   │ agent  (build từ           │  FastAPI, user appuser,             │
│   │ 02-docker/production)      │  uvicorn 2 workers, KHÔNG mở cổng   │
│   │ :8000                      │  ra host                            │
│   └──────┬──────────────┬──────┘                                     │
│          │ REDIS_URL    │ QDRANT_URL                                  │
│          ▼              ▼                                             │
│   ┌────────────┐  ┌──────────────┐                                   │
│   │ redis:6379 │  │ qdrant:6333  │                                   │
│   │ cache,     │  │ vector DB    │                                   │
│   │ rate limit │  │ cho RAG      │                                   │
│   └─────┬──────┘  └──────┬───────┘                                   │
│         ▼                ▼                                            │
│    volume redis_data   volume qdrant_data                             │
└──────────────────────────────────────────────────────────────────────┘
```

**Các service giao tiếp thế nào:**

- Cả 4 container nằm chung network bridge `internal` và gọi nhau bằng **tên service** nhờ DNS nội bộ của Docker (`agent`, `redis`, `qdrant`). IP thực tế: redis 172.20.0.2, qdrant 172.20.0.3, agent 172.20.0.4, nginx 172.20.0.5.
- Chỉ **nginx** mở cổng ra host (80/443). Agent chỉ có `8000/tcp` bên trong network: gọi thẳng `curl http://localhost:8000/health` từ host không kết nối được, mọi request phải đi qua Nginx. Log agent cho thấy request đến từ `172.20.0.5` (chính là nginx).
- `depends_on` với `condition: service_healthy`: agent chỉ khởi động sau khi redis và qdrant báo healthy (log `up` cho thấy thứ tự redis/qdrant `Healthy` → agent `Started` → nginx `Started`).
- Secret đọc từ `env_file: .env.local` (đã nằm trong `.gitignore`), không ghi trong compose.

**Test qua Nginx:**

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":18.5,"version":"2.0.0","timestamp":"2026-11-26T07:58:26.738435"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

$ curl http://localhost/ready
{"ready":true}

$ curl http://localhost:8000/health     # gọi thẳng agent, bỏ qua nginx
(không kết nối được — agent không mở cổng ra host)
```

Header `Server: nginx` và các security header (`X-Frame-Options`, …) chứng tỏ response đi qua Nginx.

Debug trong stack:

```text
$ docker compose -p k5-day14-docker exec agent sh -c 'whoami; cat /proc/1/cmdline'
appuser
/usr/local/bin/python3.11 /home/appuser/.local/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2

$ docker compose -p k5-day14-docker logs agent
agent-1  | {"time":"2026-11-26 07:58:08,355","level":"INFO","msg":"Agent ready"}
agent-1  | {"time":"2026-11-26 07:58:26,782","level":"INFO","msg":"{"event": "request", "q_len": 21}"}
agent-1  | INFO:     172.20.0.5:54270 - "POST /ask HTTP/1.1" 200 OK
```

Nhận xét: khác với image develop, container production chạy bằng `appuser` (không phải root), uvicorn là PID 1. Dòng log thứ hai **không phải JSON hợp lệ** (chuỗi JSON bị lồng vào trong `"msg":"..."` mà không escape dấu `"`), đúng lỗi đã ghi ở Part 1 khi format log được ghép chuỗi bằng tay. Dọn stack: `docker compose -p k5-day14-docker down`.

## Part 3: Cloud Deployment

Theo hướng dẫn K5, deploy chính agent Part 6 (`06-lab-complete/`) thay vì app mẫu `03-cloud-deployment/`. Chi tiết: [DEPLOYMENT.md](DEPLOYMENT.md).

### Exercise 3.1: Railway deployment

- URL: **https://agent-production-ffd58773.up.railway.app**
- Screenshot: [dashboard](screenshots/dashboard.png) · [running](screenshots/running.png) · [test](screenshots/test.png)

Các bước đã làm (Railway CLI 5.75.0, chạy trong `06-lab-complete/`):

```text
railway login
railway init                                   # project day14-agent
railway add -d redis                           # service Redis
railway add -s agent && railway service link agent
railway variable set AGENT_API_KEY --stdin ... # key ngẫu nhiên, không vào lịch sử shell
railway variable set 'REDIS_URL=${{Redis.REDIS_URL}}' ...
railway variable set ENVIRONMENT=production / RATE_LIMIT_PER_MINUTE=10 / DAILY_BUDGET_USD=1.0 / LOG_LEVEL=INFO
railway up --service agent                     # build theo railway.toml + Dockerfile
railway domain --service agent                 # sinh URL public
```

File `06-lab-complete/.railwayignore` loại `.env` khỏi phần upload của `railway up`, nên key test ở máy không bị gửi lên Railway.

Kiểm tra URL public:

```text
$ curl -i https://agent-production-ffd58773.up.railway.app/health
HTTP/1.1 200 OK
Server: railway-hikari
{"status":"ok","uptime_seconds":515.7,"environment":"production"}

$ curl -i https://agent-production-ffd58773.up.railway.app/ready
HTTP/1.1 200 OK
{"ready":true}

$ curl -i -X POST https://agent-production-ffd58773.up.railway.app/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
www-authenticate: ApiKey
{"detail":"Missing or invalid API key. Include header: X-API-Key: <your-key>"}

POST /ask với key sai          → 401
GET  /docs                     → 404   (ENVIRONMENT=production tắt Swagger UI)
POST /ask với AGENT_API_KEY    → 200
```

Bốn lệnh tự kiểm CP6: **200 · 200 · 401 · 200**. `/ready` trả 200 nghĩa là agent trên Railway đã kết nối được Redis trên Railway.

**Cách đặt biến môi trường trên cloud:** đặt bằng `railway variable set` (hoặc tab Variables trên dashboard), Railway inject vào container lúc chạy, nên image và repo không chứa secret. `PORT` do Railway tự cấp. `REDIS_URL` dùng biến tham chiếu `${{Redis.REDIS_URL}}`, nên khi Redis đổi mật khẩu hay host thì agent tự nhận giá trị mới sau khi redeploy.

**Cách xem logs:** `railway logs --service agent` (hoặc tab Deployments → View logs). Log app là JSON, nên lọc được theo `event`, `status`, `path`.

### Exercise 3.2: So sánh `railway.toml` với `render.yaml`

So sánh hai file mẫu trong `03-cloud-deployment/` (`railway/railway.toml`, `render/render.yaml`) và hai file tôi viết cho Part 6:

| Khía cạnh | `railway.toml` | `render.yaml` |
|-----------|----------------|---------------|
| Định dạng, phạm vi | TOML, cấu hình **một service** (build + deploy). Project, database, biến môi trường tạo riêng bằng CLI/dashboard | YAML Blueprint, mô tả **cả hạ tầng**: nhiều service (web + Redis/Key Value) trong một file, Infrastructure as Code |
| Cách build | `[build] builder = "NIXPACKS"` (mẫu, tự nhận diện Python) hoặc `"DOCKERFILE"` (bản của tôi) | `runtime: python` + `buildCommand: pip install ...` (mẫu) hoặc `runtime: docker` + `dockerfilePath` (bản của tôi) |
| Lệnh chạy | `startCommand = "uvicorn app:app --host 0.0.0.0 --port $PORT"`; với builder Dockerfile thì dùng `CMD` của image | `startCommand: uvicorn ... --port $PORT`; với `runtime: docker` thì dùng `CMD` |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | Khai báo rõ: `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | Không có trong file, Render tự restart theo health check |
| Biến môi trường & secret | **Không** khai báo trong file; đặt bằng `railway variable set` / dashboard | Khai báo trong `envVars`: giá trị thường ghi thẳng, secret dùng `sync: false` (nhập tay trên dashboard) hoặc `generateValue: true` (Render tự sinh) |
| Redis / database | Thêm bằng lệnh `railway add -d redis`, nối bằng biến tham chiếu `${{Redis.REDIS_URL}}` | Khai báo service `type: redis` (mẫu cũ) / `type: keyvalue` ngay trong file, nối bằng `fromService: ... property: connectionString` |
| Vị trí file, cách deploy | Đặt trong thư mục deploy; `railway up` upload code từ máy | Blueprint ở gốc repo; Render kéo code từ GitHub (`autoDeploy: true` khi push) |
| Thông số khác | — | `region: singapore`, `plan: free`, tuỳ chọn `disk` |

**Vì sao khác:** Railway thiên về thao tác nhanh bằng CLI: file chỉ lo cách build/chạy một service, còn hạ tầng và secret quản lý ngoài file. Render coi `render.yaml` là nguồn sự thật cho toàn bộ hạ tầng (đi theo GitOps, push là deploy), nên phải mô tả cả service phụ trợ và cách cấp secret mà không ghi giá trị vào git. Cả hai đều yêu cầu app lắng nghe theo `$PORT` và có endpoint health check.

### Exercise 3.3: Cloud Run CI/CD pipeline

Đọc `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` và `service.yaml`:

1. **Test:** khi push lên `main`, Cloud Build chạy step `test` trong image `python:3.11-slim`: cài requirements + pytest và chạy `pytest tests/`. Test fail thì pipeline dừng, không build.
2. **Build:** step `build` build Docker image, gắn 2 tag `ai-agent:$COMMIT_SHA` (truy vết đúng commit, rollback được) và `:latest`, dùng `--cache-from :latest` để tận dụng layer cache.
3. **Push:** step `push` đẩy cả 2 tag lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy:** step `deploy` chạy `gcloud run deploy` với image theo `$COMMIT_SHA` ở `asia-southeast1`: public, 1–10 instance (min 1 để tránh cold start), 512 MiB / 1 CPU, timeout 60 s; secret lấy từ **Secret Manager** (`--set-secrets`), không ghi trong file.
5. **`service.yaml`** mô tả cùng service đó theo kiểu khai báo (Knative), dùng với `gcloud run services replace`: autoscaling 1–10, `containerConcurrency: 80`, `livenessProbe` gọi `/health`, `startupProbe` gọi `/ready`, `AGENT_API_KEY` và `OPENAI_API_KEY` lấy từ `secretKeyRef`.

## Part 4: API Security

Chạy trong WSL2 (Python 3.11.18). Token đã được che trong mọi output.

### Exercise 4.1: API Key authentication (`04-api-gateway/develop`)

**Trả lời câu hỏi:**

- **API key được check ở đâu?** Trong hàm dependency `verify_api_key` (dòng 39–54). Header được khai báo bằng `APIKeyHeader(name="X-API-Key", auto_error=False)` (dòng 36), và endpoint `/ask` gắn nó qua `_key: str = Depends(verify_api_key)` (dòng 70). FastAPI chạy dependency **trước** khi vào thân hàm, nên request không có key hợp lệ không bao giờ chạm tới LLM. `/` và `/health` không gắn dependency nên vẫn public (platform cần gọi `/health`).
- **Sai key thì sao?** Thiếu header → **401** `Missing API key`. Có header nhưng sai giá trị → **403** `Invalid API key.` (dòng 49–53). Lưu ý: Part 6 yêu cầu **cả thiếu lẫn sai đều trả 401**, nên không được chép nguyên logic này.
- **Rotate key thế nào?** Key đọc từ biến môi trường `AGENT_API_KEY` (dòng 35), nên rotate = đặt giá trị mới trên platform (Railway/Render variables, hoặc `.env`) rồi restart/redeploy, không cần sửa code. Vì app chỉ nhận **một** key, lúc đổi thì client đang dùng key cũ bị 403 ngay. Rotate không gián đoạn cần cho phép nhiều key cùng lúc (vd `AGENT_API_KEYS=old,new`), phát key mới cho client, rồi mới gỡ key cũ.

**Vấn đề còn lại trong bản develop:** dòng 35 có giá trị mặc định `"demo-key-change-in-production"`, quên đặt env thì app vẫn chạy với key ai cũng biết; dòng 91 `print(f"API Key: {API_KEY}")` in key ra log lúc khởi động; so sánh bằng `!=` thay vì `hmac.compare_digest` (có thể bị timing attack).

**Test** (`AGENT_API_KEY=secret-key-123 python app.py`):

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production`)

**JWT flow** (`auth.py`):

1. Client gửi `POST /auth/token` với username/password. `authenticate_user` so với `DEMO_USERS`; sai → 401.
2. `create_token` tạo payload `{"sub": username, "role": role, "iat": now, "exp": now + 60 phút}` và ký bằng **HS256** với `JWT_SECRET`.
3. Client gửi token ở header `Authorization: Bearer <token>` cho mọi request sau.
4. `verify_token` (dependency của `/ask`) gọi `jwt.decode(...)`: kiểm tra chữ ký và hạn dùng. Không có header → 401; hết hạn → 401 `Token expired`; chữ ký sai/token rác → 403 `Invalid token`. Hợp lệ thì trả `{username, role}` mà **không cần tra database**: đó là lý do JWT gọi là stateless.

Payload của JWT chỉ được **mã hoá base64, không bị mã hoá bí mật**: ai có token cũng đọc được nội dung (bên dưới tôi decode mà không cần secret). Chữ ký chỉ đảm bảo không ai **sửa** được payload. Vì vậy không được để dữ liệu nhạy cảm trong payload, và `JWT_SECRET` phải đặt bằng env (bản mẫu có giá trị mặc định `super-secret-change-in-production-please` ở `auth.py:22`, nếu quên đặt env thì ai cũng tự ký được token admin).

```text
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"wrong"}'
HTTP/1.1 401 Unauthorized

{"detail":"Invalid credentials"}

$ curl -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
{"access_token": "eyJhbGciOiJI...<đã che>", "token_type": "bearer", "expires_in_minutes": 60, "hint": "Include in header: Authorization: Bearer eyJ<đã che>"}

# decode phần payload của token (base64), không cần secret:
{'sub': 'student', 'role': 'user', 'iat': 1795680287, 'exp': 1795683887}     # exp - iat = 3600 s = 60 phút

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer abc.def.ghi" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 403 Forbidden

{"detail":"Invalid token."}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK

{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":""}'
HTTP/1.1 422 Unprocessable Entity          # AskRequest: min_length=1, max_length=1000
```

### Exercise 4.3: Rate limiting

**Trả lời câu hỏi** (`rate_limiter.py`):

- **Thuật toán:** **sliding window log**. Mỗi user có một `deque` lưu timestamp các request. Mỗi lần `check()`: bỏ các timestamp cũ hơn 60 giây ở đầu deque → nếu số còn lại ≥ limit thì 429, ngược lại thêm timestamp hiện tại. Khác với fixed window (đếm theo từng phút cố định, cho phép dồn 2× limit quanh mốc chuyển phút) và token bucket (cho phép burst rồi nạp dần).
- **Giới hạn:** user thường (`student`, role `user`) **10 request / 60 giây**; admin (`teacher`, role `admin`) **100 request / 60 giây** (dòng 86–87). Khi bị chặn trả 429 kèm header `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.
- **Bypass cho admin:** `app.py:141` chọn limiter theo role trong JWT: `rate_limiter_admin if role == "admin" else rate_limiter_user`. Admin không được bypass hoàn toàn mà chỉ được hạn mức cao hơn (100/phút). Muốn bypass hẳn thì bỏ qua `limiter.check()` khi `role == "admin"`, nhưng giữ một trần cao vẫn an toàn hơn (token admin bị lộ thì không bị spam vô hạn).
- **Hạn chế:** state nằm trong RAM của process. Restart là mất bộ đếm; chạy nhiều worker/instance thì mỗi process đếm riêng, limit thực tế nhân lên theo số process. Part 6 phải chuyển sang Redis (sorted set).

**Test:** đã dùng 1 request ở 4.2, vòng lặp gửi thêm 20 request với token `student`:

```text
$ for i in $(seq 1 20); do curl -s -o /tmp/r.json -w '%{http_code}' -X POST http://localhost:8000/ask \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"question\": \"Test $i\"}"; done
Request 1: HTTP 200  {"question":"Test 1","answer":"Agent đang hoạt động tốt! ..."}
Request 2: HTTP 200
...
Request 9: HTTP 200  {"question":"Test 9","answer":"Tôi là AI agent được deploy lên cloud. ..."}
Request 10: HTTP 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":60}}
Request 11: HTTP 429
...
Request 20: HTTP 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":60}}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"one more"}'
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795680347
retry-after: 60
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":60}}
```

Request thứ 11 tính cả request ở 4.2 (request 10 trong vòng lặp) bị chặn: đúng 10 request/phút.

Cùng lúc đó, `teacher` (role admin) gửi 15 request liên tiếp đều qua, vì dùng limiter 100/phút; còn `student` gọi `/admin/stats` bị 403:

```text
teacher, 15 request: 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200
$ curl -i http://localhost:8000/admin/stats -H "Authorization: Bearer $TOKEN"     # student
HTTP/1.1 403 Forbidden
$ curl http://localhost:8000/admin/stats -H "Authorization: Bearer $TEACHER_TOKEN"
{"total_users":"N/A (in-memory demo)","global_cost_usd":0.00046050000000000013,"global_budget_usd":10.0}
```

### Exercise 4.4: Cost guard implementation

**Bản mẫu `cost_guard.py` làm gì:**

- Mỗi user một `UsageRecord` theo ngày (input/output tokens, số request). Chi phí = `input/1000 × $0.00015 + output/1000 × $0.0006` (giá GPT-4o-mini).
- `check_budget()` chạy **trước** khi gọi LLM: tổng toàn hệ thống ≥ `$10/ngày` → **503**; chi phí của user ≥ `$1/ngày` → **402 Payment Required**; ≥ 80% → log cảnh báo.
- `record_usage()` chạy **sau** khi gọi LLM, cộng token và cộng vào chi phí toàn cục.
- Đổi ngày thì `_get_record` tạo record mới, tức là reset hằng ngày.

Usage thật sau 10 request của `student`:

```text
$ curl http://localhost:8000/me/usage -H "Authorization: Bearer $TOKEN"
{"user_id":"student","date":"2026-11-26","requests":10,"input_tokens":40,"output_tokens":292,"cost_usd":0.000181,"budget_usd":1.0,"budget_remaining_usd":0.999819,"budget_used_pct":0.0}
```

Với mock, mỗi request chỉ tốn khoảng $0.000018, nên phải ~55,000 request mới chạm $1. Để thấy 402 và 503, tôi gọi trực tiếp class `CostGuard` với budget rất nhỏ (200 input + 100 output token mỗi lần = $0.00009):

```text
# CostGuard(daily_budget_usd=0.0001)
Request 1: OK  cost=$0.000090
User student at 90% budget                        ← cảnh báo 80%
Request 2: OK  cost=$0.000180
Request 3: HTTP 402 {'error': 'Daily budget exceeded', 'used_usd': 0.00018, 'budget_usd': 0.0001, 'resets_at': 'midnight UTC'}

# CostGuard(daily_budget_usd=1.0, global_daily_budget_usd=0.00005)
global user1: OK  global=$0.000090
global user2: HTTP 503 Service temporarily unavailable due to budget limits. Try again tomorrow.
GLOBAL BUDGET EXCEEDED: $0.0001
```

Request 2 vẫn qua dù sau đó vượt budget, vì `check_budget` chỉ so chi phí **đã dùng** với budget, chưa cộng chi phí ước tính của request sắp gọi. Hệ quả: user có thể vượt budget tối đa một request.

**Cách làm với Redis (yêu cầu của bài):** budget $10/tháng mỗi user, lưu trong Redis, reset đầu tháng.

```python
import redis
from datetime import datetime

r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
MONTHLY_BUDGET_USD = float(os.getenv("MONTHLY_BUDGET_USD", "10"))

def check_budget(user_id: str, estimated_cost: float) -> bool:
    month_key = datetime.now().strftime("%Y-%m")          # vd "2026-11"
    key = f"budget:{user_id}:{month_key}"
    current = float(r.get(key) or 0)
    if current + estimated_cost > MONTHLY_BUDGET_USD:      # tính cả request sắp gọi
        return False                                       # endpoint trả 402
    r.incrbyfloat(key, estimated_cost)
    r.expire(key, 32 * 24 * 3600)                          # tự xoá sau 32 ngày
    return True
```

- **Reset đầu tháng** không cần cron: key chứa tháng (`budget:student:2026-11`), sang tháng 12 code tự đọc key mới `budget:student:2026-12` (bắt đầu từ 0). `EXPIRE` 32 ngày để key tháng cũ tự bị xoá.
- **Vì sao Redis:** mọi worker/instance đọc chung một bộ đếm, và restart app không mất số tiền đã tiêu (bản in-memory mất sạch khi restart, user lại có budget mới).
- Đã chạy thử với một container `redis:7-alpine` tạm:

```text
call 1: estimated=$4.0  -> OK           spent=$4.00
call 2: estimated=$4.0  -> OK           spent=$8.00
call 3: estimated=$1.5  -> OK           spent=$9.50
call 4: estimated=$1.0  -> BLOCK (402)  spent=$9.50     ← 9.5 + 1.0 > 10
call 5: estimated=$0.5  -> OK           spent=$10.00    ← vừa đúng 10, vẫn cho qua
key: budget:student:2026-11 | TTL (ngày): 32.0

$ redis-cli get budget:student:2026-11
10
```

- **Điểm cần cải thiện:** `GET` rồi mới `INCRBYFLOAT` là hai lệnh riêng, hai request song song có thể cùng đọc $9.50 rồi cùng được cộng thêm, vượt budget. Cách chặt hơn: `INCRBYFLOAT` trước, nếu kết quả > budget thì trừ lại và trả 402 (hoặc gói trong một Lua script / `MULTI`). Ngoài ra nên ghi chi phí **thật** sau khi LLM trả về (dựa trên token thực tế) thay vì chỉ chi phí ước tính.

**Vì sao cần cả rate limit lẫn cost guard:** rate limit bảo vệ **tốc độ** (chống spam, chống một client chiếm hết tài nguyên trong thời gian ngắn), cost guard bảo vệ **tiền** (tổng chi phí theo ngày/tháng). Chỉ có rate limit: 10 req/phút × 1440 phút = 14,400 request/ngày cho mỗi user, với prompt dài và model đắt vẫn có thể ra hóa đơn lớn. Chỉ có cost guard: một client vẫn có thể bắn hàng nghìn request/giây làm sập service trước khi chạm budget. Hai lớp bổ sung cho nhau.

### Lỗi nhỏ phát hiện trong bản mẫu production

- `app.py:160` trả `"budget_remaining_usd": usage.total_cost_usd`, tức là trả số **đã dùng**, không phải số còn lại (response ở 4.2 cho `1.6e-05` trong khi còn gần $1). `/me/usage` thì tính đúng (`0.999819`).
- `/me/usage` cho `"budget_used_pct": 0.0` vì làm tròn 1 chữ số thập phân (0.018% → 0.0).
- Tất cả state (rate limit, cost) nằm trong RAM, chạy với `reload=True` nên chỉ có 1 process, chưa thấy vấn đề; khi chạy nhiều worker sẽ đếm sai.

## Part 5: Scaling & Reliability

Chạy trong WSL2 (Python 3.11.18), Docker Desktop.

### Exercise 5.1: Health checks (`05-scaling-reliability/develop`)

**Liveness vs readiness:**

| | `/health` (liveness) | `/ready` (readiness) |
|---|---|---|
| Câu hỏi | Process còn sống không? | Có nên gửi traffic vào instance này không? |
| Ai gọi | Platform / orchestrator (Docker `HEALTHCHECK`, Railway, Kubernetes `livenessProbe`) | Load balancer, Kubernetes `readinessProbe` |
| Fail thì sao | **Restart** container | **Ngừng gửi traffic** tới instance đó (không restart) |
| Nên kiểm tra | Chỉ những gì chứng tỏ process còn chạy được, **không** phụ thuộc DB/Redis | Đã khởi động xong, dependency (Redis, DB) kết nối được, không đang shutdown |

Lý do tách đôi: nếu `/health` cũng ping Redis, khi Redis chết **mọi** instance cùng bị đánh giá "chết" và bị restart liên tục, dù restart không sửa được Redis (restart storm). Đúng ra instance chỉ nên tạm rút khỏi load balancer (`/ready` → 503) và tự quay lại khi Redis lên. Đây cũng là tiêu chí của Part 6: `/health` luôn 200, `/ready` 503 khi mất Redis.

**Code mẫu đã cài như thế nào:** `develop/app.py` dùng cờ `_is_ready`: bật `True` sau khi lifespan khởi động xong (dòng 49), tắt `False` khi bắt đầu shutdown (dòng 55). `/ready` trả 503 khi cờ là `False`. Bản production (`production/app.py:208`) kiểm tra thêm `_redis.ping()`, Redis lỗi → 503.

Cách cài cho agent thật có Redis:

```python
@app.get("/health")
def health():
    return {"status": "ok", "uptime_seconds": round(time.time() - START_TIME, 1)}

@app.get("/ready")
def ready():
    if not _is_ready:
        raise HTTPException(503, "starting up or shutting down")
    try:
        r.ping()
    except Exception:
        raise HTTPException(503, "redis not available")
    return {"ready": True}
```

**Test** (`python app.py`):

```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T08:18:16.366427+00:00","checks":{"memory":{"status":"ok","used_percent":12.9}}}

$ curl http://localhost:8000/ready
{"ready":true,"in_flight_requests":1}
```

(`in_flight_requests` là 1 vì middleware đếm luôn chính request `/ready`.)

### Exercise 5.2: Graceful shutdown

**Cơ chế:** khi deploy bản mới hoặc scale down, platform gửi **SIGTERM** (có thể bắt được), chờ một khoảng (Docker mặc định 10 s), hết giờ mới gửi **SIGKILL** (không bắt được). Trong khoảng đó app phải: (1) ngừng nhận request mới, (2) làm xong request đang chạy, (3) đóng kết nối (Redis, DB), (4) thoát với exit code 0.

Trong code mẫu, uvicorn làm phần lớn việc này: nhận SIGTERM → đóng socket listen → chờ request đang chạy xong (tối đa `timeout_graceful_shutdown=30`) → chạy phần shutdown của `lifespan` (đặt `_is_ready = False`, chờ `_in_flight_requests` về 0, đóng tài nguyên) → thoát.

**Test:** gửi một `/ask` (mock LLM mất ~3 s), sau 0.5 s gửi `kill -TERM`:

```text
$ python app.py &  PID=$!
$ curl -X POST "http://localhost:8000/ask?question=Long%20task" &
$ sleep 0.5; kill -TERM $PID

[client] {"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
[client] HTTP 200 sau 3.037948s
[server] exit code = 0
```

Log server:

```text
INFO:     Shutting down                                                   ← nhận SIGTERM, ngừng nhận request mới
INFO:     127.0.0.1:35464 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK   ← request đang chạy vẫn hoàn thành
INFO:     Waiting for application shutdown.
2026-11-26 15:13:59,286 INFO 🔄 Graceful shutdown initiated...
2026-11-26 15:13:59,286 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [2376]
2026-11-26 15:13:59,286 INFO Received signal 15 — uvicorn will handle graceful shutdown

$ curl http://localhost:8000/health        # sau khi tắt
connection refused
```

**Kết luận:** request đang chạy **vẫn hoàn thành với 200** dù SIGTERM đến giữa chừng, server thoát với exit code 0.

**Quan sát thêm:**

- Dòng `Received signal 15` của `handle_sigterm` xuất hiện **sau cùng**, không phải lúc nhận tín hiệu. Lý do: `uvicorn.run()` cài handler SIGTERM của chính nó lúc khởi động, đè lên handler đăng ký ở dòng 186; khi tắt xong uvicorn khôi phục handler cũ và phát lại tín hiệu, nên handler của app chỉ chạy ở cuối. Vì thế handler tự viết **không được** tự gọi `sys.exit()` hay chặn tín hiệu; nếu muốn ghi log lúc nhận SIGTERM thì phải gọi lại handler trước đó (đúng như gợi ý ở Part 6 Step 7).
- **Event loop bị chặn:** `ask_agent` là `async def` nhưng gọi `ask()` có `time.sleep(3)` (hàm đồng bộ). Trong 3 giây đó cả server bị đứng:

  ```text
  /health trong lúc /ask đang chạy: HTTP 200 sau 2.712175s
  /health lúc rảnh:                 HTTP 200 sau 0.000773s
  ```

  Health check chậm 2.7 s có thể bị platform coi là timeout và restart container dù app vẫn sống. Sửa bằng cách khai báo endpoint là `def` (FastAPI chạy trong threadpool) hoặc `await asyncio.to_thread(ask, question)`, hoặc dùng client LLM bất đồng bộ.

### Exercise 5.3: Stateless design

**Vì sao state trong RAM hỏng khi scale:** mỗi instance là một process riêng với bộ nhớ riêng. Nếu lưu `conversation_history = {}` trong RAM: request 1 của user A vào instance 1 (history lưu ở instance 1), request 2 bị load balancer chuyển sang instance 2, ở đó không có history của A → agent "quên" cuộc trò chuyện. Thêm nữa, restart hay deploy lại là mất sạch, và mỗi instance có bộ đếm rate limit/cost riêng nên giới hạn bị nhân lên theo số instance.

**Cách làm đúng** (`production/app.py`): mọi state nằm ngoài process, trong Redis:

- `save_session` ghi `session:<id>` bằng `SETEX` với TTL 3600 s, `load_session` đọc lại bằng `GET` (dòng 59–73).
- `append_to_history` đọc session → thêm message → giữ tối đa 20 message → ghi lại.
- Client giữ `session_id` và gửi kèm mỗi request; instance nào nhận cũng đọc được cùng một history.
- Instance không còn gì "riêng", nên có thể thêm, bớt, restart bất kỳ instance nào mà không mất dữ liệu.

Hạn chế còn lại của code mẫu:

- `append_to_history` là đọc → sửa → ghi (không atomic): hai request cùng session đến hai instance cùng lúc có thể ghi đè message của nhau. Dùng `RPUSH` + `LTRIM` trên Redis list sẽ atomic hơn.
- Nếu không kết nối được Redis lúc khởi động, app **tự động chuyển sang dict trong RAM** (dòng 42–45) và vẫn báo healthy. Khi chạy nhiều instance thì đây chính là lỗi stateful ở trên, chỉ khác là bị che đi. Production nên fail (`/ready` 503) thay vì âm thầm dùng RAM.
- Trường `turn` trong response bị lệch +1 (`app.py:154`): `history` được đọc **sau khi** đã thêm câu hỏi hiện tại, rồi lại cộng thêm 1. Ở thí nghiệm bên dưới, câu thứ 2 của session trả `turn=3`.

### Exercise 5.4: Load balancing

Chạy trong `05-scaling-reliability/production/` (sau `touch .env.local`):

```text
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
NAME                       STATUS                            PORTS
k5-day14-scaling-agent-1   Up 4 seconds (health: starting)   8000/tcp
k5-day14-scaling-agent-2   Up 4 seconds (health: starting)   8000/tcp
k5-day14-scaling-agent-3   Up 4 seconds (health: starting)   8000/tcp
k5-day14-scaling-nginx-1   Up 4 seconds                      0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 18 seconds (healthy)           6379/tcp
```

Gửi 10 request qua Nginx (`POST http://localhost:8080/chat`), đọc `served_by` trong body và header `X-Served-By` (địa chỉ upstream Nginx chọn):

```text
Request 1:  served_by=instance-c7809a  X-Served-By=172.20.0.4:8000
Request 2:  served_by=instance-43e638  X-Served-By=172.20.0.3:8000
Request 3:  served_by=instance-1924d3  X-Served-By=172.20.0.5:8000
Request 4:  served_by=instance-c7809a  X-Served-By=172.20.0.4:8000
Request 5:  served_by=instance-43e638  X-Served-By=172.20.0.3:8000
Request 6:  served_by=instance-1924d3  X-Served-By=172.20.0.5:8000
Request 7:  served_by=instance-c7809a  X-Served-By=172.20.0.4:8000
Request 8:  served_by=instance-43e638  X-Served-By=172.20.0.3:8000
Request 9:  served_by=instance-1924d3  X-Served-By=172.20.0.5:8000
Request 10: served_by=instance-c7809a  X-Served-By=172.20.0.4:8000

$ docker compose -p k5-day14-scaling logs agent | grep "POST /chat"     # đếm theo instance (gồm cả 5 request của test_stateless)
      5 agent-1
      6 agent-2
      4 agent-3
```

**Nhận xét:** Nginx chia đều theo kiểu **round-robin** (instance 1 → 2 → 3 → 1 …). `server agent:8000` trong `nginx.conf` được Docker DNS phân giải thành IP của cả 3 container, Nginx coi đó là 3 upstream server. Agent không mở cổng ra ngoài, mọi traffic đi qua Nginx ở cổng 8080.

**Khi 1 instance chết:** giữa một cuộc hội thoại, chạy `docker stop k5-day14-scaling-agent-1`:

```text
session=8efc6d59-675e-4103-9936-30d52583d2be      (turn 1 gửi trước khi stop)
$ docker stop k5-day14-scaling-agent-1
turn 2: HTTP 200 served_by=instance-1924d3 turn=3
turn 3: HTTP 200 served_by=instance-c7809a turn=4
turn 4: HTTP 200 served_by=instance-1924d3 turn=5
turn 5: HTTP 200 served_by=instance-c7809a turn=6
history count = 10
  [user] turn 1 truoc khi kill
  [user] turn 2 sau khi kill
  [user] turn 3 sau khi kill
  [user] turn 4 sau khi kill
  [user] turn 5 sau khi kill
```

Không request nào lỗi: traffic chỉ còn chia cho 2 instance còn lại (nhờ `proxy_next_upstream error timeout http_503`, Nginx thử upstream khác khi một upstream không kết nối được), và history vẫn đủ 5 lượt vì nằm trong Redis.

### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
============================================================
Stateless Scaling Demo
============================================================

Session ID: c135f92f-bc89-4634-95e0-a92b63da28fa

Request 1: [instance-c7809a]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-43e638]
  Q: Why do we need containers?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 3: [instance-1924d3]
  Q: What is Kubernetes?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 4: [instance-c7809a]
  Q: How does load balancing work?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 5: [instance-43e638]
  Q: What is Redis used for?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-43e638', 'instance-1924d3', 'instance-c7809a'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: How does load balancing work?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Redis used for?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:** 5 câu hỏi trong **cùng một session** được 3 instance khác nhau xử lý (c7809a → 43e638 → 1924d3 → c7809a → 43e638, đúng thứ tự round-robin). Nếu history lưu trong RAM, mỗi instance chỉ thấy 1–2 câu của riêng nó; ở đây history đọc lại đủ **10 message (5 user + 5 assistant) theo đúng thứ tự**, chứng tỏ state nằm trong Redis dùng chung chứ không ở instance nào. Script không tự tắt instance nào, nên tôi làm thêm hai thí nghiệm:

- Tắt 1 instance giữa cuộc hội thoại (kết quả ở 5.4): mọi request vẫn 200, history vẫn đủ.
- **Restart toàn bộ agent** (`docker compose -p k5-day14-scaling restart agent`, Redis giữ nguyên): sau restart, instance có ID mới (`instance-ee0351`) nhưng history của session vẫn còn:

  ```text
  sau restart: history count = 10
  {"status":"ok","instance_id":"instance-ee0351","uptime_seconds":3.9,"storage":"redis","redis_connected":true}

  $ docker compose -p k5-day14-scaling exec redis redis-cli --scan --pattern 'session:*' | wc -l
  12
  $ docker compose -p k5-day14-scaling exec redis redis-cli ttl session:8efc6d59-...
  3594          # session tự hết hạn sau 1 giờ
  ```

Dọn stack: `docker compose -p k5-day14-scaling down`.

## Part 6: Final Project — output `check_production_ready.py`

Chạy bản **đầy đủ** (có Docker) trong WSL2: `cd 06-lab-complete && python check_production_ready.py`. Kết quả: `Result: 12/12 tiêu chí đạt · 43/43 checks passed`, exit code 0.

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số dòng chi tiết từ cùng lần chạy:

```text
     ✅ Docker: build image thành công — 21s
     ✅ Docker: image < 500 MB — 273 MB
     ✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429
     ✅ Khi chạy: hết budget → 402 — 402 ở request thứ 1
     ✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 10 dòng JSON
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.7s
```

### Thiết kế

| File | Làm gì |
|------|--------|
| `app/config.py` | `Settings` dataclass, mọi giá trị đọc bằng `os.getenv` (`PORT`, `ENVIRONMENT`, `LOG_LEVEL`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`). `AGENT_API_KEY` mặc định rỗng, không có secret trong code |
| `app/logging_config.py` (mới) | `JsonFormatter` dùng `json.dumps` cho cả dòng log (escape đúng mọi ký tự, tránh lỗi ghép chuỗi ở Part 1–2). Logger `agent` ghi ra stdout, `propagate=False` |
| `app/auth.py` | `APIKeyHeader("X-API-Key", auto_error=False)`; thiếu, sai, hoặc server chưa cấu hình key → **401**. So sánh bằng `hmac.compare_digest` (chống timing attack) |
| `app/redis_client.py` | `redis.from_url` không kết nối ngay khi import → container khởi động được khi chưa có Redis. Timeout 2 s; `redis_healthy()` ping cho `/ready` |
| `app/rate_limiter.py` | Sliding window 60 s trên Redis sorted set: `ZREMRANGEBYSCORE` → `ZCARD` → vượt thì **429** + `Retry-After` → `ZADD` + `EXPIRE`. Khoá theo `sha256(api_key)` (không lưu key thô trong Redis) |
| `app/cost_guard.py` | Tổng chi phí trong ngày ở key `cost:daily:<YYYY-MM-DD>`; `check_budget()` ≥ `DAILY_BUDGET_USD` → **402**; `record_cost()` cộng bằng `INCRBYFLOAT` (atomic) + `EXPIRE` 2 ngày. Sang ngày mới là key mới nên tự reset |
| `app/main.py` | `lifespan` (startup/shutdown), middleware log JSON mỗi request (kèm `request_id`, `status`, `ms`), handler lỗi Redis → 503 và lỗi bất ngờ → 500 không lộ stack trace, `/health`, `/ready`, `/ask` |
| `Dockerfile` | Multi-stage: builder tạo venv `/opt/venv` và `pip install`; runtime `python:3.11-slim` sạch, copy venv + `app/` + `utils/`, user `app` (non-root), `HEALTHCHECK`, `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000} --workers 2"]` |
| `docker-compose.yml` | `agent` (build từ Dockerfile, `env_file: .env` với `required: false`, `REDIS_URL=redis://redis:6379/0`, `depends_on: redis: service_healthy`) + `redis:7-alpine` có healthcheck và volume |
| `.dockerignore` | Loại `.env`, `.env.*` (giữ `.env.example`), `__pycache__`, `venv`, `.git`, tài liệu, `check_production_ready.py`, `benchmark-observability/` |
| `railway.toml` / `render.yaml` | Railway: `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`. Render: web service Docker + Key Value (Redis), `AGENT_API_KEY` dùng `generateValue: true`, `REDIS_URL` lấy từ `fromService` |

Luồng `POST /ask`: `verify_api_key` (401) → `check_rate_limit` (429) → `check_budget` (402) → gọi LLM → `record_cost`.

**Vì sao `/health` luôn 200 khi Redis chết còn `/ready` trả 503:** `/health` là liveness, fail thì platform **restart** container. Restart không sửa được Redis, nên nếu `/health` phụ thuộc Redis thì Redis chết sẽ kéo theo mọi instance bị restart liên tục. `/ready` là readiness, fail thì load balancer chỉ **ngừng gửi traffic** tới instance đó cho tới khi Redis quay lại.

**Graceful shutdown:** không tự đăng ký handler SIGTERM (tránh đè handler của uvicorn như đã thấy ở Part 5). uvicorn nhận SIGTERM → ngừng nhận kết nối mới → chờ request đang chạy xong → chạy phần shutdown của `lifespan` (đặt `ready = False`, log `shutdown`, đóng kết nối Redis) → thoát exit code 0. `exec` trong CMD để uvicorn là PID 1 và nhận SIGTERM trực tiếp từ `docker stop`.

**Không chặn event loop:** `/ask` khai báo `def` (không `async`), FastAPI chạy nó trong threadpool. Khác với Part 5 (`/health` chậm 2.7 s khi `/ask` đang chạy), ở đây `/health` trong lúc `/ask` đang chạy trả lời sau **0.00094 s**.

### Test thủ công với `docker compose`

`cp .env.example .env`, đặt `AGENT_API_KEY` ngẫu nhiên, `docker compose -p k5-day14-final up -d --build`:

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.2,"environment":"development"}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
www-authenticate: ApiKey
{"detail":"Missing or invalid API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing or invalid API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: $AGENT_API_KEY" -H "Content-Type: application/json" -d '{"question":"What is deployment?"}'
HTTP/1.1 200 OK
{"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"cost_usd":1.2e-05,"requests_remaining":9}}
```

**Xử lý lỗi input:** mã lỗi rõ ràng, chỉ ra trường bị sai, không có stack trace:

```text
-d '{"question":""}'      → HTTP 422 {"detail":[{"type":"string_too_short","loc":["body","question"],"msg":"String should have at least 1 character",...}]}
-d '{"q":"Hello"}'        → HTTP 422 {"detail":[{"type":"missing","loc":["body","question"],"msg":"Field required",...}]}
-d 'khong phai json'      → HTTP 422 {"detail":[{"type":"json_invalid","loc":["body",0],"msg":"JSON decode error",...}]}
```

**Rate limit** (`RATE_LIMIT_PER_MINUTE=10`, đã dùng 4 request ở trên):

```text
200 200 200 200 200 200 200 200 200 429
HTTP/1.1 429 Too Many Requests
retry-after: 59
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

**State trong Redis:**

```text
$ docker compose -p k5-day14-final exec redis redis-cli --scan
ratelimit:95b852c97e0b4dba
cost:daily:2026-11-26
$ docker compose -p k5-day14-final exec redis redis-cli get cost:daily:2026-11-26
0.00011595
```

**Tắt Redis** (`docker compose -p k5-day14-final stop redis`):

```text
/health: 200
/ready:  {"detail":"Redis not available"}  (HTTP 503)
/ask:    {"detail":"Service temporarily unavailable (state store)"}  (HTTP 503)
/ready sau khi bật lại Redis: {"ready":true}  (HTTP 200)
```

`/ask` không còn kiểm tra được rate limit và budget nên trả 503 (fail closed) thay vì cho qua. Khi Redis chết, request `/ask` mất khoảng 4 s mới trả 503 (timeout kết nối 2 s, redis-py thử lại).

**Log JSON** (`docker compose -p k5-day14-final logs agent`): 22 dòng bắt đầu bằng `{`, cả 22 parse được bằng `json.loads`:

```text
{"ts": "2026-11-26T08:36:44.709+00:00", "lvl": "INFO", "logger": "agent", "msg": "request", "event": "request", "request_id": "82e49c734dc6", "method": "POST", "path": "/ask", "status": 200, "ms": 105.2}
{"ts": "2026-11-26T08:36:44.714+00:00", "lvl": "INFO", "logger": "agent", "msg": "request", "event": "request", "request_id": "5eb1e0203db0", "method": "POST", "path": "/ask", "status": 429, "ms": 0.8}
{"ts": "2026-11-26T08:36:53.313+00:00", "lvl": "ERROR", "logger": "agent", "msg": "redis_error", "event": "redis_error", "path": "/ask", "error": "ConnectionError"}
{"ts": "2026-11-26T08:36:53.314+00:00", "lvl": "INFO", "logger": "agent", "msg": "request", "event": "request", "request_id": "1be55e268cb3", "method": "POST", "path": "/ask", "status": 503, "ms": 4002.6}
```

**`docker stop`:** exit code **0** sau 0.8 s:

```text
INFO:     Waiting for application shutdown.
{"ts": "2026-11-26T08:36:58.258+00:00", "lvl": "INFO", "logger": "agent", "msg": "shutdown", "event": "shutdown", "uptime_s": 15.0}
INFO:     Application shutdown complete.
INFO:     Finished server process [9]
```

---

## Part 7: Benchmark & Observability

Số liệu benchmark (load test, eval, scaling) nằm trong [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md). Mục này ghi câu trả lời các câu hỏi không có chỗ trong mẫu báo cáo.

### Exercise 7.1: Đọc metrics của agent

Chạy `AGENT_VERSION=v1 PORT=8001 python app.py` và `AGENT_VERSION=v2 PORT=8002 python app.py` trong `06-lab-complete/benchmark-observability/develop/`. Output bên dưới lấy từ một instance v2 chạy thêm ở cổng 8003 **sau khi đã thêm metric mới**, gồm 5 câu hỏi và 5 URL lạ:

```text
$ curl -s -X POST http://localhost:8003/ask -H "Content-Type: application/json" -d '{"question": "Prometheus thu thập metrics như thế nào?"}'
{"answer":"Prometheus pull metrics bằng cách scrape endpoint /metrics theo chu kỳ. Counter chỉ tăng (đếm request), Gauge lên xuống (request đang xử lý), Histogram chia latency vào các bucket để tính percentile bằng histogram_quantile.","model":"mock-llm-small","agent_version":"v2","usage":{"input_tokens":91,"output_tokens":55,"cost_usd":4.665e-05},"llm_latency_ms":165.0,"request_id":"ac9e5b998d3e"}
```

**Câu 1: Ví dụ cho mỗi loại metric** (`curl -s http://localhost:8003/metrics | grep -v "^#"`):

| Loại | Ví dụ trong output | Ý nghĩa |
|------|--------------------|---------|
| **Counter**: chỉ tăng, về 0 khi restart | `http_requests_total{method="POST",route="/ask",status="200"} 5.0`<br>`llm_tokens_total{model="mock-llm-small",type="input"} 330.0`<br>`llm_cost_usd_total{model="mock-llm-small"} 0.0001425` | Đếm tích luỹ. Muốn biết "bao nhiêu mỗi giây" thì dùng `rate(http_requests_total[1m])` trong Prometheus |
| **Gauge**: lên xuống tuỳ ý | `agent_in_flight_requests 0.0`<br>`agent_info{model="mock-llm-small",version="v2"} 1.0` | Giá trị tức thời: số request đang xử lý (lúc scrape không có request nào nên = 0). `agent_info` là gauge luôn = 1, chỉ dùng label để biết version/model đang chạy |
| **Histogram**: đếm quan sát theo bucket | `http_request_duration_seconds_bucket{le="0.2",method="POST",route="/ask"} 5.0`<br>`http_request_duration_seconds_count{method="POST",route="/ask"} 5.0`<br>`http_request_duration_seconds_sum{method="POST",route="/ask"} 0.9036801570036914` | Mỗi bucket `le="x"` đếm số request có latency ≤ x giây (bucket **cộng dồn**). Có `_count` và `_sum` nên tính được trung bình (0.904 / 5 = 181 ms) và percentile bằng `histogram_quantile(0.95, rate(..._bucket[5m]))` |

**Câu 2: Vì sao dùng `route.path` thay vì `request.url.path` làm label `route`.**

Mỗi tổ hợp giá trị label khác nhau là **một time series riêng** mà Prometheus phải lưu trong RAM. Tôi gửi 5 URL lạ giống bot quét (`/wp-admin`, `/.env`, `/a1b2c3`, `/admin/config.php`, `/xyz123`), cả 5 đều 404 và **gộp vào một series**:

```text
http_requests_total{method="GET",route="unmatched",status="404"} 5.0
http_request_duration_seconds_count{method="GET",route="unmatched"} 5.0
```

Nếu dùng URL thật, mỗi URL lạ sinh ra 1 series cho counter **cộng thêm 14 series** cho histogram (12 bucket + `_count` + `_sum`), tức **15 series mỗi URL**. Bot quét 10,000 URL thì có thêm khoảng **150,000 series**. Đây là **cardinality bùng nổ**: Prometheus hết RAM, query chậm, dashboard treo, và kẻ tấn công có thể cố ý gây ra (DoS vào hệ thống giám sát). Dùng route template (`/ask`, `/health`, hoặc `unmatched`) thì số series là hữu hạn và biết trước, bất kể client gọi URL gì. Cùng lý do đó, không bao giờ dùng `user_id`, `request_id` hay nội dung câu hỏi làm label.

**Nhiệm vụ: thêm metric `agent_question_length_chars`** (`develop/app.py`):

```python
QUESTION_LENGTH = Histogram(
    "agent_question_length_chars", "Độ dài câu hỏi gửi tới /ask (ký tự)",
    buckets=(20, 50, 100, 200, 500, 1000, 2000),
)

# trong ask(), trước khi gọi LLM:
QUESTION_LENGTH.observe(len(body.question))
```

- **Dùng Histogram, không dùng label `length=...`**, vì độ dài câu hỏi có vô số giá trị (1 đến 2000), làm label sẽ gây đúng vấn đề cardinality ở câu 2. Histogram chỉ tạo đúng 10 series cố định (8 bucket + `_count` + `_sum`).
- Bucket chọn theo giới hạn `max_length=2000` của `AskRequest`.
- Đặt **trước** khi gọi LLM, để cả request bị lỗi LLM cũng được đếm.

Kết quả sau 5 câu hỏi dài 2, 13, 40, 97 và 275 ký tự (tổng 427):

```text
agent_question_length_chars_bucket{le="20.0"} 2.0
agent_question_length_chars_bucket{le="50.0"} 3.0
agent_question_length_chars_bucket{le="100.0"} 4.0
agent_question_length_chars_bucket{le="200.0"} 4.0
agent_question_length_chars_bucket{le="500.0"} 5.0
agent_question_length_chars_bucket{le="1000.0"} 5.0
agent_question_length_chars_bucket{le="2000.0"} 5.0
agent_question_length_chars_bucket{le="+Inf"} 5.0
agent_question_length_chars_count 5.0
agent_question_length_chars_sum 427.0
```

Đọc ra: 2 câu ≤ 20 ký tự, 3 câu ≤ 50, 4 câu ≤ 100, cả 5 câu ≤ 500; độ dài trung bình = 427 / 5 = 85.4 ký tự.

### Exercise 7.4: Observability stack

Chạy trong `06-lab-complete/benchmark-observability/production/`: `docker compose -p k5-day14-observability up -d --build` (agent ×2, Nginx, Prometheus, Grafana, Jaeger, Locust). Tải: Locust **30 users, ramp up 5**. Ảnh dashboard: [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png).

**Sự cố khi bật stack, và cách sửa:** lần đầu cả 2 container agent crash liên tục (`Restarting (1)`), log báo `ModuleNotFoundError: No module named 'uvicorn'`, nên Nginx trả 502/504 cho mọi request. Nguyên nhân nằm ở `production/Dockerfile` mẫu: stage builder cài package bằng `pip install --user` vào `/root/.local`, rồi copy sang `/home/agent/.local`; nhưng user chạy app được tạo bằng `useradd -d /app`, tức `HOME=/app`, nên Python tìm package `--user` ở `/app/.local` và không thấy gì. Sửa bằng một dòng `ENV PYTHONUSERBASE=/home/agent/.local` (đúng lỗi mà CODE_LAB Part 6 Step 8 đã cảnh báo), rồi `docker compose -p k5-day14-observability up -d --build agent`. Sau đó cả 2 agent `healthy`, `/ask` trả 200 có header `X-Trace-ID`, `X-Served-By`, và 20 request được chia 11 / 9 cho 2 instance.

**Đọc từ ảnh [`grafana-dashboard.png`](screenshots/grafana-dashboard.png)** (hàng Golden Signals, Last 15 minutes): Traffic **16.1 req/s**, Error rate **1.32%**, Latency p95 **290.26 ms**, Saturation (in-flight) **5**, Instances up **2**, LLM cost (1h) **$0.2048**. Panel "Requests/s theo instance": 2 đường `172.20.0.5:8000` và `172.20.0.6:8000` chồng gần như trùng nhau, mỗi đường ~8 req/s. Panel "Latency /ask": p50/p95/avg nằm sát nhau quanh 0.2–0.3 s, còn p99 tách hẳn lên ~1.8 s.

Số liệu chi tiết hơn đọc trực tiếp từ Prometheus (cùng câu PromQL với các panel), lúc Locust 30 users đã chạy ổn định vài phút:

| Chỉ số | Giá trị |
|--------|---------|
| Traffic `/ask` | 16.36 req/s |
| Error rate `/ask` | 0.97% |
| p50 / p95 / p99 `/ask` | 171.9 ms / 293.9 ms / 1850.5 ms |
| avg `/ask` | 236.4 ms |
| LLM p95 | 198.3 ms |
| Req/s theo instance | `172.20.0.5:8000`: 8.19 · `172.20.0.6:8000`: 8.17 |
| Tokens/s | input 1190.0 · output 635.0 |
| Cost ước tính | $1.79 / giờ |
| In-flight / Instances up | 6 / 2 |

**Câu 1: p95 và avg đang là bao nhiêu? Khoảng cách giữa chúng nói lên điều gì?**

p95 = **293.9 ms**, avg = **236.4 ms**, chênh khoảng 58 ms, nhưng p99 = **1850.5 ms**, gấp gần 8 lần avg. Phân bố latency **lệch phải**: đa số request xong trong khoảng 170–300 ms, còn một nhóm nhỏ (~3% do `MOCK_SLOW_RATE=0.03`) bị cộng thêm khoảng 1.5 s. Nhóm này quá nhỏ để kéo p95 lên (3% < 5%), chỉ làm avg nhích lên một chút, nhưng p99 thì thấy rõ. Khoảng cách giữa avg và p99 trên panel "Latency" chính là **tail latency**; nếu chỉ nhìn avg (236 ms) thì tưởng mọi thứ tốt, trong khi cứ 100 request lại có vài request chờ gần 2 giây. (Lưu ý: p95 tính từ histogram bằng nội suy trong bucket 0.2–0.3 s, nên là giá trị ước lượng; LLM p95 = 198 ms rơi ngay dưới mốc bucket 0.2 s, còn HTTP p95 cộng thêm retrieval ~20 ms và overhead nên rơi vào bucket kế tiếp.)

**Câu 2: Panel "Requests/s theo instance": Nginx có chia đều traffic cho 2 instance không?**

**Có, gần như tuyệt đối đều:** 8.19 và 8.17 req/s (chênh 0.2%). Nginx dùng round-robin mặc định cho `upstream agent_cluster`, và `server agent:8000 resolve` khiến Nginx hỏi Docker DNS mỗi 10 giây để biết danh sách IP của các container `agent`. Ngay sau khi tạo lại container agent, trong khoảng 10 giây đầu mọi request đều đi vào một IP (Nginx còn giữ kết quả DNS cũ), sau đó mới chia đều 11 / 9 trên 20 request.

**Câu 3: Vì sao input tokens/s lớn hơn output tokens/s?**

Input ≈ **1190** tokens/s, output ≈ **635** tokens/s (gấp ~1.9 lần). Mỗi lần gọi LLM, prompt (input) gồm **system prompt + tài liệu retrieve được từ knowledge base (RAG) + câu hỏi**, trong khi câu trả lời (output) chỉ là nội dung trả lời. Ở agent v2, prompt luôn chứa nguyên văn tài liệu, nên input luôn dài hơn output. Đây cũng là đặc điểm chung của RAG: chi phí chủ yếu nằm ở context nhồi vào prompt. Muốn giảm chi phí thì cắt bớt context (top_k nhỏ hơn, tài liệu ngắn hơn) hoặc cache prompt. Ngược lại, giá output đắt hơn input (với `mock-llm-small`, như GPT-4o-mini thì gấp 4 lần) nên phải theo dõi cả hai.

**Câu 4: `curl http://localhost:8080/metrics` trả về gì? Vì sao?**

```text
$ curl -i http://localhost:8080/metrics
HTTP/1.1 404 Not Found
Server: nginx/1.28.3
```

Trả **404 từ chính Nginx** (header `Server: nginx`, trang lỗi HTML của Nginx), request không hề tới agent. `nginx/nginx.conf` có:

```nginx
# /metrics chỉ dành cho Prometheus (scrape trực tiếp trong mạng nội bộ).
location = /metrics {
    return 404;
}
```

`/metrics` lộ thông tin nội bộ (danh sách route, lưu lượng, tỉ lệ lỗi, chi phí, phiên bản đang chạy), có ích cho kẻ tấn công thăm dò hệ thống, và scrape liên tục cũng tốn tài nguyên. Prometheus không đi qua Nginx mà **scrape thẳng từng container** trong mạng Docker nội bộ (`http://172.20.0.5:8000/metrics`, `http://172.20.0.6:8000/metrics`, cả hai `up`), nhờ `dns_sd_configs` tìm IP các instance. Đi qua Nginx cũng sai về mặt đo lường: mỗi lần scrape sẽ trúng ngẫu nhiên một instance, số liệu nhảy lung tung.

**Ghi chú về số liệu Locust:** lúc agent còn crash, Locust đã ghi nhận 110 lỗi 502 và 46 lỗi 504 (Nginx không kết nối được upstream). Sau khi sửa Dockerfile, trong 60 giây tiếp theo hai con số này không tăng thêm; lỗi mới chỉ có 503, là lỗi upstream giả lập của mock (~1%, khớp error rate 0.97% ở trên). Bộ đếm Locust đã được reset để số liệu về sau sạch.

---

## AI log

| # | Phần | Hỏi gì | Nhận gì | Tự kiểm tra thế nào |
|---|------|--------|---------|---------------------|
| 1 | CP0 | Nhờ Claude Code kiểm tra môi trường | Phát hiện WSL chỉ có Python 3.10 và Docker chưa bật WSL integration; hướng dẫn cài Python 3.11 + venv và bật integration | Tự chạy lại `python --version` (3.11.18), `os.name` (`posix`), `docker run --rm hello-world` trong WSL |
| 2 | Part 1 | Nhờ Claude Code làm CP1: đọc `develop/app.py` và `production/app.py`, chạy hai bản và viết câu trả lời | Danh sách anti-pattern, output curl thật của hai bản, bảng so sánh, ghi chú về lỗi log JSON và `.env` không được nạp | Đã đọc lại toàn bộ phần này, hiểu và xác nhận nội dung; số liệu lấy từ output lệnh và file report thật |
| 3 | Part 2 | Nhờ Claude Code làm CP2: đọc 2 Dockerfile + compose, build 2 image, chạy container và stack, viết câu trả lời | Trả lời 4 câu Ex 2.1, số đo kích thước image, sơ đồ stack, output test qua Nginx | Đã đọc lại toàn bộ phần này, hiểu và xác nhận nội dung; số liệu lấy từ output lệnh và file report thật |
| 4 | Part 4 | Nhờ Claude Code làm CP3: đọc code `04-api-gateway`, chạy bản develop + production, test 401/403/200/429, test cost guard (in-memory và Redis) | Câu trả lời 4.1–4.4, output `curl -i` (token đã che), giải thích thuật toán rate limit và cost guard bằng Redis, danh sách lỗi nhỏ trong bản mẫu | Đã đọc lại toàn bộ phần này, hiểu và xác nhận nội dung; số liệu lấy từ output lệnh và file report thật |
| 5 | Part 5 | Nhờ Claude Code làm CP4: chạy bản develop (health/ready, SIGTERM giữa request), chạy stack 3 instance + `test_stateless.py`, thử tắt 1 instance và restart toàn bộ agent | Câu trả lời 5.1–5.5, output thật, phát hiện event loop bị chặn bởi `time.sleep` trong `async def` và lỗi lệch `turn` | Đã đọc lại toàn bộ phần này, hiểu và xác nhận nội dung; số liệu lấy từ output lệnh và file report thật |
| 6 | Part 6 | Nhờ Claude Code làm CP5: đọc bản khung `06-lab-complete/` và `check_production_ready.py` (không sửa script chấm), viết code cho các TODO, chạy script chấm đầy đủ và test bằng `docker compose` | Code `app/*.py` (thêm `app/logging_config.py`), `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`; `PASS 12/12` | Đã đọc lại toàn bộ phần này, hiểu và xác nhận nội dung; số liệu lấy từ output lệnh và file report thật |
| 7 | Part 3 | Nhờ Claude Code hướng dẫn CP6: các lệnh Railway CLI (tạo project, thêm Redis, đặt biến, deploy, tạo domain); sau khi tôi tự deploy, nhờ kiểm tra URL và viết `DEPLOYMENT.md`, so sánh `railway.toml`/`render.yaml`, tóm tắt pipeline Cloud Run | Hướng dẫn từng lệnh, file `.railwayignore`, `DEPLOYMENT.md`, mục Part 3 | Tôi tự chạy các lệnh Railway và đặt `AGENT_API_KEY` trên Railway; tự chạy 4 lệnh tự kiểm ra 200/200/401/200 |
| 8 | Part 7 (Ex 7.1) | Tôi tự tạo `BENCHMARK_REPORT.md`, tự chạy agent v1/v2 và đọc `/metrics`; nhờ Claude Code thêm metric `agent_question_length_chars` và viết câu trả lời 7.1 | Code Histogram trong `develop/app.py`, output `/metrics` thật (instance thử ở cổng 8003), giải thích Counter/Gauge/Histogram và cardinality | Đã đọc lại toàn bộ phần này, hiểu và xác nhận nội dung; số liệu lấy từ output lệnh và file report thật |
| 9 | Part 7 (Ex 7.2–7.3) | Tôi tự chạy load test (7.2a, 7.2b), eval v1/v2 và eval cuối; nhờ Claude Code điền bảng 2.1, 2.2, mục 1 và 3 của `BENCHMARK_REPORT.md`, thêm 2 entry `KNOWLEDGE_BASE` (JWT, HPA) và viết `.github/workflows/eval.yml` | Số liệu chép từ các file JSON trong `develop/reports/`, phân tích nút thắt ở c=100 bằng `/metrics`, kiểm tra offline không regression, chạy thử job CI (v2 exit 0, v1 exit 1) | Đã đọc lại toàn bộ phần này, hiểu và xác nhận nội dung; số liệu lấy từ output lệnh và file report thật |
| 10 | Part 7 (CP8, Ex 7.4–7.7) | Tôi tự bật stack, chụp 4 ảnh Grafana/Jaeger/Prometheus và tự làm thí nghiệm A+B lần đầu; nhờ Claude Code sửa lỗi `production/Dockerfile` (thiếu `PYTHONUSERBASE` khiến agent crash), lấy số liệu Prometheus cho 7.4, tìm trace chậm/lỗi và dòng log khớp `trace_id`, chạy thí nghiệm C/D/E và đo lại A+B bằng script đọc `/api/v1/alerts`, chạy Locust headless scale 1/3, điền mục 4–6 `BENCHMARK_REPORT.md`, copy `reports/` và `benchmark-results/` | Dockerfile đã sửa, câu trả lời 7.4, bảng thời gian tới lúc firing, phân tích scaling (tải closed-loop chưa bão hoà; nút thắt là LLM latency), kết luận | Đã đọc lại toàn bộ phần này, hiểu và xác nhận nội dung; số liệu lấy từ output lệnh và file report thật |
