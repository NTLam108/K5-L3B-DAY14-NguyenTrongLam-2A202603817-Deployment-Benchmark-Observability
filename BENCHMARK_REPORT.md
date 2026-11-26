# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Nguyễn Trọng Lâm
**Ngày chạy:** 2026-11-26
**Môi trường:** Windows 11 + WSL2 Ubuntu 22.04 (20 CPU logic), Python 3.11.18, Docker Desktop 29.9.3. Agent và `load_test.py` chạy trên cùng máy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Chatbot trả lời dưới ~0.5 s người dùng vẫn thấy "tức thì". Đặt theo p95 (không theo average) để bắt được tail latency. Mức này có biên an toàn so với latency bình thường (p95 ≈ 215–231 ms khi c ≤ 50, mục 2.1) và bị vi phạm đúng lúc hệ thống thật sự quá tải (c=100) hoặc khi > 5% request chậm (mục 2.2) |
| Error rate `/ask` | < 2 % | Mock LLM có ~1% lỗi upstream (`MOCK_ERROR_RATE=0.01`), đo được 0.67–2.00%. Ngưỡng 2% là error budget cho phép lỗi upstream ngẫu nhiên, nhưng sẽ báo khi lỗi tăng gấp đôi trở lên |
| Accuracy trên golden dataset | ≥ 85 % | Ngưỡng quality gate trong CI (`--min-accuracy 0.85`): cho phép sai tối đa 3/23 câu để không chặn PR vì câu hỏi mới chưa kịp bổ sung tài liệu, nhưng chặn ngay phiên bản tệ như v1 (4.35%). Kèm điều kiện **không regression** so với phiên bản trước |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.31 | 188.7 | 217.9 | 1702.9 | 0.67% (2/300) | ✅ |
| 10 | 38.5 | 186.8 | 215.6 | 1671.1 | 2.00% (6/300) | ✅ (error rate vừa chạm ngưỡng 2%) |
| 50 | 119.32 | 193.9 | 231.3 | 1685.8 | 1.33% (4/300) | ✅ |
| 100 | 72.2 | 291.3 | 2445.6 | 2748.0 | 1.33% (4/300) | ❌ (p95 > 500 ms) |

Nguồn: `develop/reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json` (`--requests 300`, agent v2 cấu hình mặc định: `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`). Mọi lỗi đều là `503` (lỗi upstream giả lập của mock LLM), không có lỗi kết nối hay timeout.

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

**Tăng gần tuyến tính ở mức thấp, sau đó chậm lại và đến c=100 thì giảm hẳn.** Theo định luật Little, nếu server không bị nghẽn thì RPS ≈ concurrency ÷ latency trung bình:

| Concurrency | avg (ms) | RPS lý thuyết = c ÷ avg | RPS đo được | Đạt |
|---|---|---|---|---|
| 1 | 233.0 | 4.29 | 4.31 | ~100% |
| 10 | 217.0 | 46.1 | 38.5 | 84% |
| 50 | 232.4 | 215.1 | 119.32 | 55% |
| 100 | 828.3 | 120.7 | 72.2 | 60% (so với tuyến tính từ c=1: 431 → chỉ đạt 17%) |

- **c=1 → c=10 → c=50:** latency gần như không đổi (p50 ≈ 187–194 ms, p95 ≈ 216–231 ms) nên RPS tăng mạnh theo concurrency (4.31 → 38.5 → 119.32). Lý do: mock LLM "chờ" bằng `asyncio.sleep` chứ không tốn CPU, nên một process uvicorn vẫn xử lý được nhiều request song song trong cùng event loop.
- **RPS vẫn thấp hơn lý thuyết, nhất là ở c=50 (55%),** một phần vì lần chạy rất ngắn: 300 request / 50 worker ≈ 6 request mỗi worker, chạy 2.51 s. Chỉ cần vài request "slow" (~1.7 s, do `MOCK_SLOW_RATE=3%`) rơi vào lượt cuối là kéo dài cả lần chạy và kéo RPS xuống. Muốn đo RPS ổn định nên chạy theo thời gian (`--duration 30`).
- **c=100: điểm gãy.** p50 tăng lên 291 ms, p95 nhảy từ 231 ms lên **2445.6 ms**, RPS **giảm** từ 119.32 xuống 72.2. Đây là lúc hệ thống bị nghẽn và request phải xếp hàng.
- **Nút thắt không nằm ở LLM hay code của `/ask`.** Histogram phía server (`/metrics` của agent v2 sau cả 4 lần chạy, 1204 request = 4 × 300 + 4 request warm-up) cho thấy server không xử lý request nào lâu quá 2 s:

  ```text
  http_request_duration_seconds_bucket{le="0.3",method="POST",route="/ask"} 1165.0
  http_request_duration_seconds_bucket{le="1.0",method="POST",route="/ask"} 1167.0
  http_request_duration_seconds_bucket{le="2.0",method="POST",route="/ask"} 1204.0
  http_request_duration_seconds_count{method="POST",route="/ask"} 1204.0
  llm_request_duration_seconds_bucket{le="0.3",model="mock-llm-small"} 1151.0
  llm_request_duration_seconds_bucket{le="2.0",model="mock-llm-small"} 1188.0
  ```

  Trong khi đó client đo ở c=100 có 10% request > 2200 ms (p90 = 2200.4 ms). Phần thời gian chênh lệch xảy ra **trước khi request vào tới middleware của app**: client mở cùng lúc 100 kết nối TCP, chờ server `accept`, và tất cả dồn vào **một process uvicorn với một event loop**; thêm nữa load generator cũng chạy trên cùng máy, tranh CPU. Metric của chính service không thấy được thời gian xếp hàng này. Đây là lý do production cần đo latency ở cả phía client hoặc load balancer, không chỉ trong app.
- **p99 ≈ 1.7 s ở mọi mức c ≤ 50** không phải do tải, mà do ~3% request bị mock cố tình làm chậm thêm 1500 ms (`MOCK_SLOW_RATE=0.03`). 3% < 5% nên p95 không bị ảnh hưởng, nhưng p99 thì có (xem mục 2.2).
- **Kết luận:** với 1 process, agent giữ được SLO tới khoảng **50 request đồng thời** (~119 RPS). Muốn chịu c=100 cần scale ngang (nhiều worker/instance sau load balancer, như Part 5 và mục 5), chứ tăng concurrency trên một process chỉ làm request xếp hàng lâu hơn.

### 2.2 Tail latency

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 188.1 | 214.3 | 219.9 |
| 0.03 (mặc định) | 228.1 | 214.8 | 1680.2 |
| 0.1 | 340.4 | 1694.2 | 1716.2 |

Nguồn: `develop/reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json` (agent v2, `--requests 300 --concurrency 20`; request "slow" bị cộng thêm `MOCK_SLOW_MS` = 1500 ms).

Số liệu phụ từ cùng các file:

| `MOCK_SLOW_RATE` | p50 (ms) | p90 (ms) | max (ms) | RPS | SLO (p95 ≤ 500 ms, lỗi ≤ 2%) |
|---|---|---|---|---|---|
| 0 | 188.9 | 211.0 | 226.1 | 103.35 | ✅ |
| 0.03 | 188.5 | 211.8 | 1710.4 | 64.85 | ✅ |
| 0.1 | 191.9 | 654.0 | 1720.7 | 48.56 | ❌ |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

**p99 nhạy nhất, rồi đến p95; average và p50 gần như "không thấy" request chậm.**

| Thay đổi | avg | p95 | p99 |
|---|---|---|---|
| 0 → 0.03 (3% request chậm) | +40.0 ms (+21%) | +0.5 ms (~0%) | **+1460.3 ms (×7.6)** |
| 0 → 0.1 (10% request chậm) | +152.3 ms (+81%) | **+1479.9 ms (×7.9)** | +1496.3 ms (×7.8) |

- **Với 3% request chậm, chỉ p99 phát hiện ra.** p99 là ngưỡng mà 1% request chậm nhất vượt qua. Khi 3% request bị cộng 1500 ms, ngưỡng này rơi đúng vào nhóm chậm nên nhảy từ 219.9 lên 1680.2 ms. p95 thì không đổi (214.3 → 214.8 ms), vì 3% < 5%: nhóm 5% chậm nhất vẫn có cả request bình thường.
- **Khi lên 10% (> 5%), p95 cũng lộ ra:** 214.3 → 1694.2 ms, vượt SLO 500 ms. p90 = 654.0 ms nằm giữa hai nhóm, đúng ở ranh giới khoảng 10% request chậm.
- **Average tăng đúng bằng phần "pha loãng" của request chậm:** khoảng tỉ lệ chậm × 1500 ms (lý thuyết +45 ms và +150 ms, đo được +40.0 và +152.3 ms). Ở mức 0.03, avg chỉ tăng từ 188 lên 228 ms, nhìn vẫn hoàn toàn "khoẻ" (vẫn dưới 500 ms rất xa).
- **p50 không đổi** (188.9 → 188.5 → 191.9 ms): người dùng "điển hình" không thấy gì, chỉ nhóm ở đuôi bị ảnh hưởng.

**Vì sao SLO không nên đặt theo average:**

1. **Average che mất người dùng bị chậm.** Ở mức 0.03, cứ 100 request thì khoảng 3 request phải chờ ~1.7 s (gấp 8 lần bình thường), nhưng average chỉ nhích từ 188 lên 228 ms. Một SLO "avg < 500 ms" sẽ báo PASS trong khi 3% người dùng đang có trải nghiệm tệ. Với một user gửi nhiều câu hỏi trong một phiên, khả năng gặp ít nhất một lần chậm còn cao hơn nhiều.
2. **Average bị kéo bởi cả hai phía và không cho biết phân bố.** Cùng một average có thể là "mọi request 228 ms" hoặc "97% request 188 ms + 3% request 1.7 s", hai trải nghiệm rất khác nhau.
3. **Percentile trả lời đúng câu hỏi của SLO:** "X% người dùng được phục vụ nhanh hơn Y ms". Vì vậy SLO đặt theo **p95** (mục 1), còn **p99** dùng để theo dõi tail latency: ở đây p99 đã báo động từ mức 3%, trước khi p95 vi phạm SLO ở mức 10%.

**Ảnh hưởng tới throughput:** RPS giảm 103.35 → 64.85 → 48.56 dù số request lỗi không tăng. `load_test.py` là kiểu *closed loop*: mỗi worker chờ xong request này mới gửi request tiếp, nên một request chậm 1.7 s giữ chỗ của worker đó suốt 1.7 s. Lần chạy cũng ngắn (2.9–6.2 s), nên vài request chậm ở cuối kéo dài cả lần chạy. Tail latency vì vậy không chỉ làm vài người dùng khó chịu mà còn làm giảm năng lực phục vụ của cả hệ thống.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.30% (21/23) | 100.00% (23/23) |
| Avg tokens / câu | 57.4 | 109.3 | 121.9 |
| Tổng cost (USD) | 0.000409 | 0.000764 | 0.000861 |
| Cost / câu đúng (USD) | 0.00040875 | 0.00003639 | 0.00003745 |
| Latency p50 / p95 (ms) | 172.7 / 188.6 | 181.9 / 218.5 | 193.1 / 215.6 |
| Quality gate | ❌ FAIL (accuracy ≥ 80%) | ✅ PASS (≥ 80%, 0 regression so với v1) | ✅ PASS (≥ 100%, 0 regression so với v2) |

Nguồn: `develop/reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`. Lệnh:

```bash
python eval/run_eval.py --url http://localhost:8001 --out reports/eval_v1.json
python eval/run_eval.py --url http://localhost:8002 --out reports/eval_v2.json --baseline reports/eval_v1.json
# sửa KNOWLEDGE_BASE, restart v2
python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
```

Cả 3 lần chạy: `errors = 0` (không câu nào fail vì lỗi 503 ngẫu nhiên). Accuracy theo category của v2 trước khi sửa: `scaling` 2/3, `security` 1/2, các category khác 100%; sau khi sửa: mọi category 100%.

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Câu hỏi | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|---|
| `security-02` | JWT khác gì API key trong xác thực? | `token`, `hết hạn`, `chữ ký` | `KNOWLEDGE_BASE` chưa có tài liệu nào về JWT, nên retrieval không tìm được gì và v2 trả lời chung chung. Thêm entry kích hoạt bởi `jwt`, `json web token`, `api key`, nội dung so sánh: API key là chuỗi cố định, không tự hết hạn, server phải tra cứu; JWT là token chứa claims và thời điểm hết hạn, được ký bằng chữ ký số nên server chỉ cần xác minh chữ ký |
| `scaling-03` | Kubernetes HPA scale dựa trên những chỉ số nào? | `cpu`, `memory`, `custom metrics` | Tương tự, chưa có tài liệu về HPA. Thêm entry kích hoạt bởi `hpa`, `kubernetes`, `autoscaler`, `autoscaling`, nội dung: HPA tăng giảm số pod theo CPU, memory hoặc custom metrics (RPS, độ dài hàng đợi, p95 latency từ Prometheus) |

Cả 2 entry thêm vào **cuối** danh sách và chỉ dùng từ khoá kích hoạt đặc trưng, vì retrieval chọn 1 tài liệu có nhiều từ khoá trùng nhất (hoà thì entry đứng trước thắng). Từ khoá chung chung như `scale` hay `key` có thể khớp nhầm câu khác (vd `scaling-01` "...stateless để **scale** ngang") và gây regression. Trước khi chạy thật, tôi kiểm tra offline bằng chính `retrieve_context()` và `score_answer()` trên cả 23 câu: chỉ `security-02` và `scaling-03` đổi tài liệu, 21 câu còn lại giữ nguyên. Eval thật xác nhận: 23/23, `Câu bị regression : 0`. Không sửa `golden_dataset.jsonl`.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** v1 không có retrieval, chỉ trả lời đúng 1/23 câu (`basic-01`, nhờ câu trả lời cứng cho từ "deploy"). v2 có RAG nên lên 21/23, rồi 23/23 sau khi bổ sung tài liệu. Accuracy của v2 phụ thuộc trực tiếp vào độ phủ của knowledge base: thiếu tài liệu thì model trả lời chung chung, và chỉ eval mới bắt được (không có lỗi HTTP nào, latency vẫn bình thường).
- **Chi phí mỗi request tăng:** v2 tốn gấp ~1.9 lần token mỗi câu (57.4 → 109.3) và gấp ~1.87 lần tổng cost (0.000409 → 0.000764 USD), vì tài liệu retrieve được ghép vào prompt và câu trả lời dài, cụ thể hơn.
- **Nhưng chi phí cho mỗi câu ĐÚNG giảm ~11 lần:** v1 tốn 0.00040875 USD để có 1 câu đúng, v2 chỉ 0.00003639 USD. v1 rẻ trên từng request nhưng gần như toàn bộ tiền bỏ ra cho câu trả lời vô dụng. Đây là lý do "cost / câu đúng" là chỉ số tốt hơn "cost / câu" khi so 2 phiên bản: nó tính cả chất lượng vào chi phí.
- **Sau khi sửa KB:** avg tokens tăng 109.3 → 121.9 và cost / câu đúng tăng nhẹ 0.00003639 → 0.00003745 USD (+2.9%), vì 2 tài liệu mới khá dài. Đổi lại được thêm 2 câu đúng (91.3% → 100%), trade-off hợp lý. Nếu cần tiết kiệm có thể viết tài liệu ngắn gọn hơn.
- **Latency:** p50 tăng nhẹ 172.7 → 181.9 → 193.1 ms (bước retrieval ~20 ms và prompt dài hơn), p95 vẫn quanh 190–220 ms, đều xa SLO 500 ms. Với agent này, đánh đổi vài chục ms để accuracy tăng từ 4% lên 100% là hoàn toàn đáng.

**Quality gate trong CI:** [`.github/workflows/eval.yml`](.github/workflows/eval.yml) chạy trên mỗi pull request (và push lên `main`) có thay đổi trong `develop/`: cài dependencies, bật agent v2 với `MOCK_ERROR_RATE=0` (tránh fail oan vì lỗi ngẫu nhiên), chờ `/health`, rồi chạy `run_eval.py --min-accuracy 0.85`. `run_eval.py` kết thúc bằng `raise SystemExit(0 if gate_ok else 1)`, với `gate_ok = accuracy ≥ min_accuracy và không có regression`. Exit code 1 làm step fail, job fail và check trên PR màu đỏ. Đặt job này là *required status check* trong branch protection của `main` thì PR không merge được. Chạy thử đúng các bước của job trên máy:

```text
AGENT_VERSION=v2 → Accuracy 100.0% (23/23) · Quality gate ✅ PASS → exit code 0 → job xanh, được merge
AGENT_VERSION=v1 → Accuracy   4.3% ( 1/23) · Quality gate ❌ FAIL → exit code 1 → job đỏ, PR bị chặn
```

---

## 4. Observability stack (production)

### 4.1 Screenshot

Stack: `docker compose -p k5-day14-observability up -d --build` trong `production/` (agent ×2, Nginx, Prometheus, Grafana, Jaeger, Locust), tải Locust 30 users / ramp 5.

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png): Traffic 16.1 req/s, Error rate 1.32%, p95 290.26 ms, Instances up 2, panel req/s theo 2 instance
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png): trace `62b0ca9…` (17:44:55), `POST /ask` 1.7 s, span `chat mock-llm-small` 1.7 s, `agent.retrieve_context` 14.1 ms. Ảnh này chụp trước khi stack bị khởi động lại; các container agent cũ đã bị tạo lại nên log của trace này không còn. Phần đối chiếu `trace_id` ↔ log ở mục 4.3 dùng một trace chậm cùng loại (`d572ef37…`, 1713.3 ms), có log JSON được lưu lại
- [x] Một trace lỗi trong Jaeger (có event `exception`): [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png): trace `7749cf2…`, `POST /ask` 503, event `exception` (`Upstream LLM error: 503 Service Unavailable (mock)`), `error.type = upstream_unavailable`
- [x] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**: [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png): **2 alert cùng FIRING** (`AgentHighErrorRate` value 0.2023, `AgentHighLatencyP95` value 1.899 s) trong thí nghiệm A+B

Unit test alert rules:

```text
$ docker run --rm -v "$PWD/prometheus:/p" --entrypoint promtool prom/prometheus:v3.16.0 test rules /p/alert_rules_test.yml
Processing test file: /p/alert_rules_test.yml
  SUCCESS
```

**Sự cố khi bật stack:** `production/Dockerfile` mẫu thiếu `ENV PYTHONUSERBASE=/home/agent/.local`. User `agent` có `HOME=/app` nên Python không tìm thấy package cài bằng `pip install --user` (đã copy sang `/home/agent/.local`), cả 2 agent crash với `No module named 'uvicorn'`, Nginx trả 502/504. Thêm dòng `ENV` trên rồi build lại agent là chạy bình thường.

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`) | **92.6 s** (pending sau 32.4 s) | "Error rate": 1.29% → 21.34% (đỏ, ngưỡng 5%); "Requests/s theo status code": đường 503 tăng vọt; "LLM calls theo kết quả": nhánh `error` tăng. Jaeger có nhiều trace `error=true` với event `exception` |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`) | **152.7 s** (pending sau 27.4 s) | "Latency p50/p95/p99": p95 290 ms → 1900 ms, p99 lên ~1.9 s, trong khi avg chỉ 221 → 593 ms và p50 gần như không đổi. Đúng như mục 2.2: khi > 5% request chậm thì p95 lộ ra |

A và B làm **cùng một lần** (đổi cả 2 biến rồi `up -d agent`) để có 2 alert firing cùng lúc cho ảnh [`prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png). Error rate vượt 5% sau khoảng 30 s vì cần thời gian để `rate[1m]` "đầy" dữ liệu mới, rồi giữ thêm `for: 1m`. Latency cần `for: 2m` nên firing sau error rate khoảng 1 phút.
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`) | **142.4 s** (pending sau 22.1 s, khi cost/giờ vượt $2) | "Cost burn rate (USD/giờ)": $1.27 → $14.02/giờ lúc firing và còn tăng (tính trên `rate[5m]`). "Latency": p95 293 → 666 ms, avg 231 → 471 ms (model lớn chậm ×2.5), chưa tới ngưỡng 1 s nên không có alert latency |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`for: 30s`) cho instance `172.20.0.3:8000` | **40.2 s** (pending sau 10.1 s) | "Instances up" 2 → 1; "Traffic" giảm 14.4 → 10.2 req/s. Locust ghi nhận lỗi 504 (Nginx chờ instance bị pause tới `proxy_read_timeout`), nhưng error rate của agent không đổi vì request đó chưa từng tới được agent |
| E | `AGENT_VERSION=v1` | **Không có** (theo dõi 3 phút) | — | "Retrieval hit ratio": 0.87 → không còn dữ liệu (v1 không retrieve); "Tokens/s": 1902 → 941; p95 lại **giảm** 291 → 198 ms; error rate 0.96% → 1.25% (vẫn ở mức lỗi ngẫu nhiên ~1%). Mọi panel hạ tầng đều xanh |

Cách đo: script đổi `.env` rồi `docker compose -p k5-day14-observability up -d agent` (hoặc `docker pause`), đánh dấu t0, sau đó đọc `GET /api/v1/alerts` của Prometheus mỗi 5 giây và ghi thời điểm alert chuyển `inactive → pending → firing`. Prometheus scrape và tính rule mỗi 5 giây. Thời gian tới lúc firing ≈ (thời gian để biểu thức vượt ngưỡng, phụ thuộc cửa sổ `rate[1m]` hay `rate[5m]`) + thời gian `for`. Ví dụ C: cost/giờ vượt $2 ngay sau 22 s, rồi phải duy trì đủ `for: 2m` mới firing ở giây 142. Locust 30 users chạy suốt các thí nghiệm. Thí nghiệm D được làm khi A+B vẫn còn bật, nên `AgentHighErrorRate` và `AgentHighLatencyP95` đã đang firing từ trước; alert mới do D gây ra chỉ là `AgentInstanceDown`.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đổi sang v1 là **lỗi chất lượng**: agent vẫn trả 200 rất nhanh, chỉ là trả lời sai (accuracy rơi từ 100% xuống 4.35% theo eval ở mục 3). Metric hạ tầng (traffic, error rate, latency, instance up) đo "service có phục vụ được không", không đo "câu trả lời có đúng không", nên tất cả vẫn xanh, thậm chí p95 còn đẹp hơn. Cần thêm các lớp sau:

1. **Eval làm quality gate trước khi deploy:** job CI `.github/workflows/eval.yml` chạy golden dataset, accuracy < 85% hoặc có regression thì chặn merge. Đổi sang v1 sẽ bị chặn từ PR (đã thử: v1 → exit code 1).
2. **Eval định kỳ trên production (synthetic check):** cứ vài phút gửi một tập câu hỏi mẫu vào endpoint thật, đẩy accuracy thành metric (vd `agent_eval_accuracy`) và alert khi giảm.
3. **Alert trên metric "proxy" của chất lượng:** retrieval hit ratio đột ngột giảm (ở đây 0.87 → không còn dữ liệu), tokens/câu giảm mạnh, tỉ lệ câu trả lời "chung chung", và `agent_info{version}` thay đổi ngoài lịch deploy.
4. **Tín hiệu từ người dùng và chấm mẫu:** nút 👍/👎, tỉ lệ người dùng hỏi lại, LLM-as-judge chấm ngẫu nhiên vài % câu trả lời thật.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được (Jaeger → Service `observable-agent` → Longest First, và tra bằng "Lookup by Trace ID"):

- `trace_id`: `d572ef371ce370e44eff1cd6a7dbd5f7`
- Tổng thời gian: **1713.3 ms** (span `POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1689.4 ms, 98.6%**)

  | Span | Thời gian | % tổng |
  |---|---|---|
  | `POST /ask` | 1713.3 ms | 100% |
  | └ `agent.run` | 1712.0 ms | 99.9% |
  |   ├ `agent.retrieve_context` | 22.4 ms | 1.3% |
  |   └ `chat mock-llm-small` (`gen_ai.request.model = mock-llm-small`, `input_tokens = 72`, `output_tokens = 40`) | 1689.4 ms | 98.6% |

- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep d572ef371ce370e44eff1cd6a7dbd5f7`):

```json
{"ts": "2026-11-26T14:01:17.800118+00:00", "level": "INFO", "service": "observable-agent", "instance": "4e60ea489f4f", "event": "llm_call", "trace_id": "d572ef371ce370e44eff1cd6a7dbd5f7", "span_id": "d11155be391b1ff0", "request_id": "de2464b14ed2", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 72, "output_tokens": 40, "cost_usd": 3.5e-05, "llm_ms": 1688.7}
{"ts": "2026-11-26T14:01:17.800477+00:00", "level": "INFO", "service": "observable-agent", "instance": "4e60ea489f4f", "event": "http_request", "trace_id": "d572ef371ce370e44eff1cd6a7dbd5f7", "span_id": "d11155be391b1ff0", "request_id": "de2464b14ed2", "method": "POST", "route": "/ask", "status": 200, "ms": 1712.9}
```

**Kết luận:** log và trace khớp nhau qua `trace_id`/`span_id`; `llm_ms = 1688.7` trong log ≈ span `chat mock-llm-small` 1689.4 ms trong Jaeger. Request chậm hoàn toàn do **LLM** (98.6%), không phải do code của agent (retrieval chỉ 1.3%). Đây là ~3% request bị mock cộng thêm ~1500 ms (`MOCK_SLOW_RATE=0.03`), gây ra p99 ≈ 1.7–1.85 s trên dashboard. Hướng xử lý nếu là LLM thật: đặt timeout + retry cho LLM call, streaming để người dùng thấy phản hồi sớm, hoặc fallback sang model nhanh hơn khi chờ quá lâu.

Trace lỗi đối chiếu tương tự: `c96f4626acb5aabc2828b18b6630f029` (116.7 ms, span `chat mock-llm-small` có status ERROR và event `exception`):

```json
{"ts": "2026-11-26T14:01:33.731783+00:00", "level": "INFO", "service": "observable-agent", "instance": "cec832fa28e7", "event": "llm_error", "trace_id": "c96f4626acb5aabc2828b18b6630f029", "span_id": "c0fee128aec987fa", "request_id": "80c4e069f8c6", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

Ghi chú: trong Jaeger có 3 trace dài ~4.9 s cùng bắt đầu lúc 14:00:48, nhưng log của chính các request đó ghi `llm_ms ≈ 188` và `ms ≈ 214`, tức container bị đóng băng (máy tạm dừng) chứ không phải độ chậm của agent. Vì vậy tôi không chọn các trace này.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 54.85 | 190 | 220 | 1700 | 68 / 7147 (0.95%), đều là 503 upstream |
| 3 | 54.64 | 190 | 220 | 1700 | 70 / 7118 (0.98%), đều là 503 upstream |

Nguồn: dòng `POST /ask` trong `production/benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv` (cùng `scale_*_failures.csv`). Lệnh (web Locust đã dừng trước khi đo để không lẫn tải):

```bash
docker compose -p k5-day14-observability up -d --scale agent=1 agent      # rồi 3
docker compose -p k5-day14-observability run --rm locust -f /mnt/locust/locustfile.py --host http://nginx \
  --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_1                 # rồi scale_3
```

Toàn bộ request (cả `/health`): scale_1 = 60.50 req/s, scale_3 = 60.40 req/s; p95 aggregated đều 220 ms.

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

**Không.** Từ 1 lên 3 instance, mọi chỉ số gần như giữ nguyên (RPS 54.85 → 54.64, p50 190 ms, p95 220 ms, p99 1700 ms, lỗi ~1%). Có hai lý do:

1. **Tải chưa đủ để 1 instance bão hoà.** Locust là tải *closed loop*: mỗi user gửi request, chờ trả lời, rồi nghỉ `between(0.5, 2)` giây (trung bình 1.25 s). 100 user chỉ tạo được khoảng 100 ÷ (1.25 s + ~0.21 s) ≈ 68 req/s, khớp với 60.5 req/s đo được (có 10 s ramp-up). Ở mức này một instance vẫn dư sức: p95 220 ms gần bằng latency của chính LLM, không có dấu hiệu xếp hàng. Thêm instance chỉ chia nhỏ cùng một lượng tải ra 3 phần, RPS không thể tăng vì nó bị giới hạn bởi số user và thời gian nghỉ, không phải bởi server.
2. **Nút thắt của latency là LLM, không phải số instance.** Mỗi request phải chờ LLM ~150–200 ms (và ~1.7 s cho ~3% request chậm, tạo ra p99 = 1700 ms). Đó là thời gian chờ dịch vụ bên ngoài, không giảm khi thêm instance: panel "LLM latency p95" giữ ~198 ms, và trace ở mục 4.3 cho thấy span `chat mock-llm-small` chiếm 98.6% thời gian. Scale ngang tăng **throughput tối đa** (chịu được nhiều request đồng thời hơn trước khi bắt đầu xếp hàng, như ở c=100 mục 2.1), nhưng không làm **từng request** nhanh hơn.

Muốn thấy lợi ích của scale cần tạo tải vượt năng lực một instance (vd tăng `-u` lên vài trăm hoặc giảm `wait_time`), khi đó bản 1 instance sẽ có p95 tăng vọt và lỗi 504, còn bản 3 instance vẫn ổn. Muốn giảm latency thì phải xử lý ở LLM: model nhanh hơn, prompt ngắn hơn, cache câu trả lời, streaming.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Percentile, không phải average.** Với 3% request chậm, avg chỉ tăng 21% nhưng p99 tăng ×7.6 (mục 2.2). SLO đặt theo p95/p99 mới phản ánh trải nghiệm của nhóm người dùng tệ nhất. Mỗi chỉ số cũng chỉ thấy phần hệ thống nơi nó được đo: ở c=100, server ghi nhận mọi request < 2 s trong khi client đo p95 = 2.4 s (mục 2.1); khi pause một instance, Locust thấy lỗi 504 nhưng error rate của agent vẫn xanh (mục 4.2-D).
  2. **Hạ tầng xanh không có nghĩa là trả lời đúng.** Đổi sang v1 làm accuracy rơi từ 100% xuống 4.35% mà không alert nào kêu, p95 còn đẹp hơn (mục 4.2-E). Phải có eval trên golden dataset làm quality gate trong CI, và "cost / câu đúng" mới là thước đo chi phí có ý nghĩa (v2 rẻ hơn v1 ~11 lần tính trên câu đúng, mục 3).
  3. **Metrics, logs và traces bổ sung cho nhau.** Dashboard cho biết *có* vấn đề (p99 cao, error rate đỏ), trace chỉ ra *ở đâu* (98.6% thời gian nằm ở span LLM), log JSON có `trace_id` nối hai thứ lại và mang chi tiết (`llm_ms`, `error`). Alert cần `for` để tránh báo động giả, nên luôn có độ trễ: 40 s (instance down) đến 2.5 phút (latency, cost).
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

  - **Chất lượng:** chạy eval định kỳ trên production và xuất `agent_eval_accuracy`, alert khi < 85%; alert khi retrieval hit ratio giảm đột ngột hoặc `agent_info{version}` đổi ngoài lịch deploy; thu thập feedback 👍/👎 của người dùng.
  - **Latency ở rìa hệ thống:** đo latency và mã lỗi tại load balancer hoặc bằng synthetic check từ bên ngoài, để bắt được lỗi 502/504 và thời gian xếp hàng mà metric trong app không thấy.
  - **Error budget burn rate:** alert theo tốc độ tiêu error budget (vd multi-window 5m + 1h) thay vì ngưỡng cố định, vừa nhạy với sự cố lớn vừa ít báo động giả.
  - **Saturation:** CPU/memory từng container, số request đang chờ, độ dài hàng đợi; alert trước khi chạm giới hạn để kịp scale (hoặc cấu hình autoscaling theo các metric này).
  - **Chi phí và an toàn:** cost theo ngày so với budget (như cost guard Part 6), tỉ lệ 429/402, token / request bất thường (dấu hiệu prompt injection hoặc lạm dụng).
  - **Phụ thuộc bên ngoài:** latency và lỗi theo từng provider/model LLM, timeout, số lần retry, trạng thái circuit breaker; alert `AgentInstanceDown` kết hợp số instance tối thiểu đang healthy.
