# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Lê Mạnh Cường
- **MSSV:** 2A202602604
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/Cuongluadu25/K4-L3-DAY13-LeManhCuong-2A202602604-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1` (cohort K4)
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602604`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt promote (trước rollback) | `evidence/10a-prompt-promote.png` |
| Prompt rollback | `evidence/10b-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | 100/100 | CP1: PASSED cả 4 mục (schema, correlation ID, enrichment, PII) |
| `validate_dashboard.py` | 6/6 (HỢP LỆ) | 6/6 (HỢP LỆ) | Contract `config/dashboard.yaml` hợp lệ từ starter |
| `pytest` | 22 passed | 26 passed | Thêm 4 test PII (CCCD, thẻ, passport, nhiều loại) |
| Số traces hợp lệ | 0 | 104 trace, trong đó **69 trace đủ 3 tầng** | CP2: thêm child observation `retriever` + `generation` |
| Số PII leak | 0 | 0 | Đã gửi PII giả vào log, scrubber che hết |
| Latency P95 / TTFT P95 | 5345 ms / 50 ms | 1203 ms / 50 ms | Xem mục 6.1 — baseline này trượt SLO và đó là phát hiện thật |
| Retrieval success rate | 100% | 100% | `tool_success` vẫn hard-code `True` trong `app/main.py` |

### 3.1. Chi tiết baseline CP0

Môi trường: code starter chưa sửa (`git status` chỉ có `submission/REPORT.md`), còn 23 `TODO`.

Các lệnh đã chạy:

```
python scripts/validate_logs.py
python scripts/validate_dashboard.py
python -m pytest -q
python scripts/load_test.py
curl http://127.0.0.1:8000/metrics
```

Kết quả `validate_logs.py` (đọc 41 dòng trong `data/logs.jsonl`):

```
Total log records analyzed: 41
Records with missing required fields: 40
Records with missing enrichment (context): 40
Unique correlation IDs found: 0
Potential PII leaks detected: 0
Estimated Score: 30/100
```

Kết quả `validate_dashboard.py`:

```
HỢP LỆ: 6/6 panel có trong dashboard contract.
```

Kết quả `/health`: `{"ok":true,"tracing_enabled":true,"incidents":{"rag_slow":false,"tool_fail":false,"cost_spike":false}}`

Metrics snapshot sau load test (`/metrics`):

```json
{"traffic":20,"latency_p50":407.0,"latency_p95":5345.0,"latency_p99":5345.0,
 "ttft_p95":50.0,"avg_cost_usd":0.0019,"total_cost_usd":0.038,
 "tokens_in_total":676,"tokens_out_total":2400,"error_breakdown":{},"quality_avg":0.88}
```

Chuỗi log baseline (chưa có `correlation_id` và metadata enrichment):

```json
{"service": "api", "payload": {"message_preview": "How should alerts be designed?"}, "event": "request_received", "level": "info", "ts": "2026-09-29T07:27:03.192614Z"}
{"service": "api", "latency_ms": 474, "ttft_ms": 50, "tokens_in": 28, "tokens_out": 122, "cost_usd": 0.001914, "quality_score": 0.9, "tool_name": "retrieval", "tool_success": true, "payload": {"answer_preview": "Starter answer..."}, "event": "response_sent", "level": "info", "ts": "2026-09-29T07:27:03.668582Z"}
```

Nhận xét: load test trả `correlation_id = MISSING` cho mọi request, xác nhận `TODO` ở `app/middleware.py` chưa được làm. `data/logs.jsonl` đã được tạo, `/health` trả `ok: true`, `tracing_enabled: true`.

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` (`app/middleware.py`) gọi `clear_contextvars()` đầu mỗi request để tránh rò rỉ context, sau đó nhận header `x-request-id` nếu khớp `^req-[0-9a-f]{8}$`, ngược lại sinh `req-<8-ký-tự-hex>` từ `uuid4().hex[:8]`. ID được bind vào structlog contextvars và gán vào `request.state.correlation_id`, rồi trả lại qua header `x-request-id` kèm `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** `user_id_hash` (SHA-256 rút gọn 12 ký tự), `session_id`, `feature`, `model`, `env`, cùng `correlation_id` và các trường chung `ts`/`level`/`service`/`event`. Bind trong `app/main.py` trước dòng `request_received` nên mọi log sau đó trong cùng request đều dùng chung context.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` trong `app/logging_config.py` được đặt **trước** `JsonlFileProcessor()` và `JSONRenderer()`, quét đệ quy mọi giá trị chuỗi trong event dict (kể cả dict/list lồng nhau). Ngoài ra `summarize_text()` cũng scrub trước khi đưa vào `payload`.
- **Cách kiểm chứng kết quả:** lần chạy cuối trên `data/logs.jsonl` (285 dòng, **121 correlation ID** duy nhất) đạt **100/100** và **0 PII leak**; đã gửi request chứa email/điện thoại/CCCD/thẻ giả và log ghi ra `[REDACTED_EMAIL]`, `[REDACTED_PHONE_VN]`, `[REDACTED_CCCD]`, `[REDACTED_CREDIT_CARD]`. Con số 11 correlation ID ở mục 4.1 là ảnh chụp tại thời điểm CP1, khi mới chỉ có 20 dòng log.

### 4.1. Kết quả CP1

Các file đã sửa: `app/middleware.py`, `app/main.py`, `app/logging_config.py`, `app/pii.py`, `tests/test_pii.py`.

```
$ python scripts/validate_logs.py
Total log records analyzed: 20
Records with missing required fields: 0
Records with missing enrichment (context): 0
Unique correlation IDs found: 11
Potential PII leaks detected: 0

+ [PASSED] Basic JSON schema
+ [PASSED] Correlation ID propagation
+ [PASSED] Log enrichment
+ [PASSED] PII scrubbing

Estimated Score: 100/100
```

Kiểm tra response header:

```
$ curl -D - -X POST http://127.0.0.1:8000/chat -H "x-request-id: req-deadbeef" ...
HTTP/1.1 200 OK
x-request-id: req-deadbeef        # ID hợp lệ do client gửi được giữ nguyên
x-response-time-ms: ...

$ curl -D - -X POST http://127.0.0.1:8000/chat -H "x-request-id: hack/../etc" ...
HTTP/1.1 200 OK
x-request-id: req-09b45817        # ID sai format bị thay bằng ID mới
```

Log thực tế sau khi gửi PII giả:

```json
{"service": "api", "payload": {"message_preview": "Email me at [REDACTED_EMAIL] or call [REDACTED_PHONE_VN]. CCCD [REDACTED_CCCD], ..."}, "event": "request_received", "feature": "policy", "user_id_hash": "5998187f3fd6", "model": "claude-sonnet-4-5", "correlation_id": "req-6d4886c8", "env": "dev", "session_id": "pii-session", "level": "info", "ts": "2026-09-29T07:32:55.501833Z"}
```

Ghi chú: đã đổi tên `data/logs.jsonl` cũ sang bản backup ngoài repo trước khi đo lại, để validator không tính các dòng baseline chưa có correlation ID.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** project Langfuse
  `day13-k4-l3a-2A202602604` (cloud.langfuse.com), dùng key pair riêng trong `.env`.
  Đếm qua SDK bằng `client.api.observations.get_many(from_start_time=..., to_start_time=..., cursor=...)`
  (phân trang bằng `meta.cursor`, không có tham số `page`).
  Trong cửa sổ 24 giờ: **104 trace**, tất cả đều có root `lab-agent-run`, và **69 trace có đủ 3 tầng
  observation** (vượt yêu cầu 10 trace).
  Lưu ý: endpoint legacy `GET /api/public/traces` trả `410
  LEGACY_API_UNAVAILABLE_FOR_NEW_ORGANIZATION` với project mới, nên phải đọc qua
  `api.observations.get_many`.
- **Cấu trúc root/retrieval/generation observations:** một trace có 3 tầng cha–con:
  - `lab-agent-run` — loại `AGENT`, root, `parent = None`.
  - `retrieval` — loại `RETRIEVER`, con của `lab-agent-run` (tạo bởi `@observe`
    trong `app/mock_rag.py`).
  - `fake-llm-generation` — loại `GENERATION`, cùng cha, mang `model`,
    `usage_details`, `cost_details` và liên kết prompt.

  Ví dụ trace `3f45a091f611da837fbcfca38118e510`: AGENT `lab-agent-run`
  (parent `None`) + RETRIEVER `retrieval` (parent `186f864c3cc27a46`) +
  GENERATION `fake-llm-generation` (cùng parent), với
  `model=claude-sonnet-4-5`, `usage={'input': 41, 'output': 138, 'total': 179}`,
  `cost=0.002193`.

- **Ghi input/output mà không đưa PII thô lên Langfuse:** cả ba `@observe` đều đặt
  `capture_input=False, capture_output=False`, nên SDK **không** tự ghi tham số
  thô (message người dùng, prompt đã dựng). Hệ quả là ban đầu mọi observation
  đều rỗng ở hai cột Input/Output, waterfall đọc được nhưng không có ngữ cảnh.
  Cách xử lý: sau khi đã có dữ liệu, từng tầng **chủ động** gọi
  `update_current_span(...)` / `update_current_generation(...)` và chỉ gửi bản
  **đã scrub PII + cắt ngắn** qua `summarize_text()`:

  ```jsonc
  // AGENT + RETRIEVER
  input : {"query_preview": "Refund policy? Email [REDACTED_EMAIL] or call [REDACTED_PHONE_VN]"}
  // GENERATION
  input : {"prompt_preview": "Feature=policy Docs=Refunds are available within 7 days ..."}
  output: {"answer_preview": "Starter answer. You should improve this output logic and add ..."}
  ```

  Kiểm chứng bằng SDK trên trace `5d54eedf905b6764e477374f3b9e8049`: cả ba tầng
  đều trả về `input`/`output` khác `None`, và ảnh 06 chụp lại sau thời điểm sửa
  hiển thị đúng hai cột này. Đây là điểm đáng chú ý vì nó cho thấy **tắt capture
  tự động không có nghĩa là mất khả năng quan sát** — chỉ cần chủ động ghi bản
  đã khử PII.

  Lưu ý khi đọc lại số liệu cũ: 20 root observation tạo trước 15:43 ngày
  2026-09-29 vẫn rỗng Input/Output vì chụp trước khi vá; 13 root tạo sau đó đều
  có đủ.
- **Cách nối trace với log:** `correlation_id` được bind vào structlog contextvars
  ở middleware, đồng thời truyền vào `propagate_attributes` của Langfuse nên mỗi
  trace mang cùng `correlation_id` với dòng log của request đó. Nhờ vậy đi từ
  dashboard → log → trace chỉ bằng một khoá.
- **Prompt name:** `day13-chat` (text prompt, có biến `{{feature}}`, `{{docs}}`,
  `{{message}}`).
- **Version/label baseline:** v1 — nhãn `baseline` (và `production` ban đầu).
- **Version/label candidate:** v2 — nhãn `candidate`; nội dung thêm ràng buộc
  *"Answer concisely in at most 3 sentences. If docs are empty, say you lack context."*
- **Trace ID của mỗi version:**
  - v1: `1af321c1e2658babf0305695725c687d` (correlation `req-37dad539`)
  - v2: `976f20562c34e2d77212a07a7d01dfcc` (correlation `req-113b0d6a`)
  - v1 sau khi rollback: `63e98c9ad9aa01bf4b7b780275b0a585` (correlation `req-3bbab66f`)

  Kiểm chứng trong Langfuse, span `fake-llm-generation` hiển thị đúng
  `prompt=day13-chat`, `version` 1 hoặc 2 tương ứng.
- **Cách promote và rollback `production`:** dùng SDK:
  `client.update_prompt(name="day13-chat", version=2, new_labels=["production"])`
  để promote v2 lên production (khi đó `baseline=v1`, `candidate=v2`,
  `production=v2`), rồi
  `client.update_prompt(name="day13-chat", version=1, new_labels=["production"])`
  để rollback về v1. Sau mỗi lần đổi label, phải chạy lại request để trace mới
  gắn đúng version — SDK cache prompt 60 giây.

  Một chi tiết đáng nhớ: lần chạy đầu, generation hiển thị
  `prompt_source: local-fallback` kèm `prompt_fetch_error: LangfuseFallback` vì
  prompt `day13-chat` chưa tồn tại trên project. Sau khi tạo prompt v1/v2 và
  buộc uvicorn reload (xoá cache 60 giây), `prompt_source` chuyển thành
  `langfuse`.

### 5.1. Một cạm bẫy khi instrument

`tests/test_agent_prompt_trace.py` monkeypatch `agent_module.get_langfuse_client`
bằng một client giả chỉ cài `get_prompt` và `update_current_span`, đồng thời
assert `client.span_updates[-1]` bằng đúng một dict metadata. Nghĩa là **không
được** gọi `update_current_generation` trong `app/agent.py` và không được thêm
`update_current_span` nào khác.

Cách xử lý: đặt `@observe` ngay tại nơi phát sinh dữ liệu — `retrieve()` trong
`app/mock_rag.py` và `FakeLLM.generate()` trong `app/mock_llm.py`. Mỗi module
import `get_langfuse_client` riêng từ `app.tracing`, nên monkeypatch của test
không chạm tới chúng. Kết quả: 26/26 test vẫn pass mà trace vẫn đủ 3 tầng.

Ràng buộc này còn ảnh hưởng tới việc ghi input/output ở root: test chỉ assert
`span_update["metadata"]` và `span_update["version"]`, **không** assert tập khoá
của cả dict, nên vẫn có thể thêm `input=`/`output=` vào chính lời gọi
`update_current_span` duy nhất đó. Điều bắt buộc là: (a) không thêm lời gọi
`update_current_span` thứ hai trong `app/agent.py`, và (b) giữ nguyên dict
`metadata`. Vì `output` chỉ biết sau khi sinh xong, lời gọi được **dời xuống
sau** `self.llm.generate(...)` — không ảnh hưởng tới assertion vì test chỉ đọc
phần tử cuối của `span_updates`.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `scripts/build_dashboard.py` đọc `data/logs.jsonl`,
  gom bucket theo phút trong cửa sổ 60 phút rồi sinh ra `dashboard.html` tự chứa
  (SVG vẽ bằng Python, không cần cài thêm gì và không cần internet). Sáu panel
  đúng theo `config/dashboard.yaml`:

  | # | Panel | Đơn vị | Nguồn | Ngưỡng |
  |---|---|---|---|---|
  | 1 | Latency percentiles và TTFT | ms | `response_sent.latency_ms`, `ttft_ms` | P95 ≤ 3000 ms |
  | 2 | Request traffic | requests/min | `request_received` | ≥ 1 req/phút |
  | 3 | Error rate và retrieval success | % | `request_failed`, `tool_success` | error ≤ 2%, retrieval ≥ 90% |
  | 4 | Cost tích luỹ trong cửa sổ | USD | `response_sent.cost_usd` | tổng ≤ 2.5 USD |
  | 5 | Input/output tokens tích luỹ | tokens | `response_sent.tokens_in/out` | tổng ≤ 50000 |
  | 6 | Quality proxy | score 0–1 | `response_sent.quality_score` | mean ≥ 0.75 |

  Kiểm tra contract: `python scripts/validate_dashboard.py` → `HỢP LỆ: 6/6 panel`.

- **SLO và lý do chọn:** `fast_successful_requests` — 99,5% request có
  `latency_ms <= 3000` trong cửa sổ 28 ngày. **Giữ nguyên ngưỡng 3000 ms sau khi
  đối chiếu baseline**, và đây là điểm đáng nói nhất của phần này: baseline đo
  được **98,889%** (89/90 request), tức **đang trượt SLO**. Nguyên nhân không
  phải latency nền cao — P50 chỉ 153 ms và TTFT rất ổn định ở 50 ms — mà là một
  outlier ở đuôi phân bố (`max = P99 = 3449 ms`). Nới ngưỡng lên ~3500 ms sẽ làm
  SLO "đạt" một cách giả tạo và che mất lỗi thật, nên tôi giữ 3000 ms để SLO còn
  giữ được vai trò cảnh báo. Việc cần làm là xử lý đuôi latency (đặt timeout cho
  retrieval), không phải sửa ngưỡng.

- **Cách tính error budget:** ngân sách lỗi = 100% − 99,5% = **0,5%**.
  Với cửa sổ 28 ngày = 40.320 phút, ngân sách tương đương **201,6 phút**
  (≈ 3 giờ 22 phút) được phép vi phạm. Trên cửa sổ quan sát 90 request, ngân sách
  cho phép đúng **0,45 request chậm**; thực tế có **1** request 3449 ms ⇒ tiêu thụ
  **222% ngân sách** ⇒ vi phạm. Đây là lý do alert 1 là `critical` chứ không phải
  `warning`.

- **Ba alert và runbook tương ứng:** cấu hình ở `config/alert_rules.yaml`,
  runbook đầy đủ ở `docs/alerts.md`.

  | Alert | Triệu chứng người dùng | Severity | Duration | Kênh Slack | Owner |
  |---|---|---|---|---|---|
  | `chat_latency_p95_high` | Chờ câu trả lời quá lâu | critical | 5m | `#alerts-oncall` | on-call LLMOps |
  | `chat_failure_and_retrieval_degraded` | Nhận lỗi / trả lời sai ngữ cảnh | critical | 2m | `#alerts-critical` | on-call LLMOps |
  | `llm_cost_burn_high` | Hoá đơn tăng bất thường | warning | 10m | `#alerts-cost` | LLMOps owner |

  Cả ba đều phát biểu theo triệu chứng, không theo tên hàm nội bộ. Alert 2 được
  cấu hình `inhibit` alert 1 để khi request lỗi hàng loạt thì on-call không bị
  nhiễu bởi latency tăng theo.

  Đã kiểm chứng ngưỡng trên chính baseline (cửa sổ trượt):
  - p95 5 phút cao nhất = **3449 ms** lúc 08:06 ⇒ alert 1 **kêu**, và kêu đúng vì
    request đó chính là request đã vượt error budget.
  - cost 10 phút cao nhất = **0,1230 USD** ⇒ alert 3 **im**, đúng như mong đợi
    (ngưỡng 0,35 USD ≈ 2,1 USD/giờ).

### 6.1. Ghi chú kỹ thuật về dashboard

Ba lỗi đã phát hiện và sửa trong quá trình dựng, ghi lại vì đều là lỗi làm sai
lệch số liệu chứ không chỉ là lỗi trình bày:

1. **Phút không có request bị vẽ thành 0.** Ban đầu các panel percentile/mean
   trả `0` cho phút rỗng, khiến P99 tụt về 0 ms và retrieval success tụt về 0%
   — trông như sự cố nghiêm trọng. Sửa: phút rỗng trả `None` và đường dữ liệu
   **bị cắt đoạn** thay vì vẽ giá trị giả.
2. **So per-minute với ngưỡng tổng là so sai đơn vị.** Cost mỗi phút (~0,002 USD)
   không thể so với ngưỡng tổng 2,5 USD trên cùng một trục. Sửa: panel 4 và 5 vẽ
   **giá trị tích luỹ**, đúng với ngưỡng tổng; số theo phút vẫn còn ở bảng dữ liệu.
3. **Nhãn cuối dòng chồng lên nhãn SLO và nhãn trục x.** Sửa bằng thuật toán thử
   vị trí, ưu tiên kéo lên và luôn giữ trong vùng vẽ.
4. **Cửa sổ thưa dữ liệu làm dữ liệu biến mất.** Điều kiện vẽ marker là
   `n <= 24` với `n` là **độ dài cửa sổ**, không phải **số điểm có dữ liệu**. Khi
   chỉ có 2 phút có request trong cửa sổ 60 phút, mỗi chuỗi chỉ còn hai đoạn
   một điểm, mà `n = 60 > 24` nên không marker nào được vẽ — `polyline` một điểm
   vẽ ra không có gì. Hậu quả: panel latency trông như trống, người đọc chỉ thấy
   vài con số trôi ở mép phải và **không thấy được cú nhảy 153 ms → 2.654 ms**.
   Sửa: đổi điều kiện sang `len(non_null) <= 24`, và khi chuỗi có ≤ 6 điểm thì
   dán nhãn **mọi** điểm thay vì chỉ điểm cuối. Ảnh 11 và 12 được chụp lại sau
   bản sửa này.

Về màu: bảng màu lấy từ `dataviz` và đã chạy `validate_palette.js` cho cả light
(`#2a78d6,#eb6834,#1baf7a,#eda100`) và dark (`#3987e5,#d95926,#199e70,#c98500`),
đều PASS. Có một WARN về contrast ở slot aqua/vàng trên nền sáng, nên đã áp dụng
điều kiện bù: mọi panel đều có legend (khi ≥2 series), nhãn trực tiếp ở điểm cuối
và một bảng dữ liệu đầy đủ — giá trị không bao giờ chỉ đọc được bằng màu.

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1` — cohort `K4`, `seed = 1311`,
  `affected_feature = monitoring`, `latency_threshold_ms = 2000`, incident `rag_slow`.
- **Khoảng thời gian điều tra:** bật incident lúc `2026-09-29T09:12:47Z`, chạy
  workload `09:13:18Z → 09:13:33Z`, tắt incident lúc `09:21:49Z`.

### 7.1. Metrics — cái gì hỏng và từ lúc nào

Panel *1. Latency percentiles và TTFT* là panel bất thường. Trong cửa sổ 60 phút,
chỉ có hai phút có dữ liệu, và khoảng cách giữa chúng là toàn bộ câu chuyện:

| Phút (UTC) | n | P50 | P95 |
|---|---|---|---|
| 08:44 | 13 | 153 ms | 1.204 ms |
| **09:13** | **5** | **2.654 ms** | **3.792 ms** |

- **Metric cụ thể:** `p95(response_sent.latency_ms)` = **3.792 ms**, vượt cả
  `latency_threshold_ms = 2000` của challenge lẫn SLO 3000 ms của bài.
- Panel *2. Request traffic* xác nhận đúng 5 request dồn vào phút 09:13.
- Hai panel còn lại **bình thường và đó mới là thông tin quan trọng**:
  *3. Error rate và retrieval success* = 0 % lỗi và 100 % retrieval success;
  *1b. TTFT P95* **phẳng ở 50 ms** ở cả hai cụm. TTFT không tăng ⇒ nút thắt
  **không** nằm ở tầng sinh token. Đây là căn cứ để loại trừ giả thuyết model chậm
  trước khi mở trace.
- Ảnh: `evidence/12-incident-metric.png`.

### 7.2. Logs — chuyện gì đã xảy ra với từng request

Lọc `data/logs.jsonl` theo `event == "response_sent"` trong phút 09:13, sắp theo
`latency_ms` giảm dần. Bản ghi đứng đầu:

```json
{"service": "api", "latency_ms": 2654, "ttft_ms": 50, "tokens_in": 35, "tokens_out": 163,
 "cost_usd": 0.00255, "quality_score": 0.8, "tool_name": "retrieval", "tool_success": true,
 "payload": {"answer_preview": "Starter answer. You should improve this output logic and add better quality chec..."},
 "event": "response_sent", "correlation_id": "req-6171d1b0", "env": "dev",
 "user_id_hash": "ed72e61117f6", "model": "claude-sonnet-4-5",
 "session_id": "k4-l3a-challenge-s05", "feature": "monitoring", "level": "info",
 "ts": "2026-09-29T09:13:33.834104Z"}
```

- **Log line:** `response_sent` với `latency_ms = 2654`.
- **correlation ID:** `req-6171d1b0` (cặp log đầy đủ: `request_received`
  `09:13:31.176Z` → `response_sent` `09:13:33.834Z`).
- Log **không** có `request_failed`: cả 5 request đều trả HTTP 200 và
  `tool_success = true`. Sự cố này **im lặng** ở tầng lỗi — nó chỉ hiện ra ở
  latency. Nếu chỉ có alert theo error rate thì đã trượt hoàn toàn.
- Ảnh: `evidence/13-incident-log.png`.

### 7.3. Traces — tại sao chậm

Tìm trace theo `correlation_id` qua `client.api.observations.get_many(...)`:

**Trace ID: `5e0149e48e35d00e3cbb77c622b87f7d`** (correlation `req-6171d1b0`)

| Span | Loại | Duration | Ghi chú |
|---|---|---|---|
| `lab-agent-run` | AGENT (root) | 2.657 ms | tổng thời gian |
| **`retrieval`** | RETRIEVER | **2.501 ms** | **chiếm 94 % root span** |
| `fake-llm-generation` | GENERATION | 151 ms | `claude-sonnet-4-5`, usage 35/163/198 |

- **Span gây ảnh hưởng:** `retrieval`.
- Kết quả lặp lại ở **cả 5 trace**, không phải một ngoại lệ đơn lẻ —
  `retrieval` = 2.501–2.502 ms và `fake-llm-generation` = 151–153 ms trong mọi
  trace. Độ lệch giữa các lần chạy gần như bằng 0, tức đây là một khoảng chờ
  cố định chứ không phải suy giảm dần.
- Ba lớp khớp nhau: 2.501 ms (`retrieval`) + 151 ms (`generation`) ≈ 2.657 ms
  (root) ≈ 2.654 ms (`latency_ms` trong log) ≈ 2.654 ms (P50 trên dashboard).
- Ảnh: `evidence/14-incident-trace.png`.

### 7.4. Root cause

`app/incidents.py` bật cờ `rag_slow`, và `app/mock_rag.py` phản ứng bằng
`time.sleep(2.5)` bên trong `retrieve()`. Toàn bộ 2,5 giây nằm gọn trong span
`retrieval`, trước khi prompt được dựng và trước khi model được gọi — nên TTFT
không hề đổi (50 ms) còn latency end-to-end tăng đúng bằng khoảng sleep.

Đây là lỗi **được tiêm vào**, và điều đáng nói là nó không hề ngụy trang: cùng
một giá trị 2,5 s xuất hiện ở cả ba lớp với sai số dưới 5 ms.

### 7.5. Một lỗi thứ hai, độc lập, phát hiện khi kiểm chứng fix

Tắt incident xong, `latency_ms` nội bộ về đúng **P50 153 ms / P95 1.306 ms** —
nhưng **client vẫn chờ 2.040–2.361 ms**. Con số này không khớp, và lý do là một
lỗi có sẵn trong code starter:

`app/main.py` khai báo `async def chat(...)` nhưng gọi thẳng `agent.run(...)` —
một hàm **đồng bộ**. Trong một coroutine, lời gọi đồng bộ chặn cả event loop, nên
5 request gửi đồng thời bị xử lý **nối tiếp**. Bằng chứng nằm ở chính log: các
mốc `request_received` cách nhau ~155 ms và **không bao giờ chồng lấn** (nếu chạy
song song thật, cả 5 phải xuất hiện trong cùng một khoảng vài ms).

Hệ quả kép: (a) người dùng chờ thời gian bằng *vị trí trong hàng đợi* nhân với
thời gian mỗi request — lúc có incident là `2,66 s × 5 ≈ 14,87 s`; (b) **SLI
`latency_ms` không nhìn thấy thời gian chờ đó**, vì nó bắt đầu đếm bên trong
`agent.run()`, sau khi request đã xếp hàng xong. Vì vậy dashboard báo P95 3.792 ms
trong khi người dùng thật chờ 14.870 ms — **sai lệch 3,9 lần**.

### 7.6. Fix action

1. **Ngay lập tức:** `python scripts/inject_incident.py --disable`.
   Đã kiểm chứng: chạy lại đúng workload challenge đó, `latency_ms` về
   P50 153 ms / P95 1.306 ms, dưới cả ngưỡng challenge 2000 ms lẫn SLO 3000 ms.
2. **Bền vững (chưa làm, đề xuất):** đặt timeout cho `retrieve()` để một truy vấn
   chậm không thể chiếm 2,5 giây của cả hệ thống.

### 7.7. Preventive measure

- **Đưa việc chặn event loop ra khỏi đường tới hạn.** Đổi `async def chat` thành
  `def chat` (FastAPI sẽ chạy trong threadpool), hoặc giữ `async` và bọc
  `await run_in_threadpool(agent.run, ...)`. Đây là bản sửa có giá trị nhất vì nó
  sửa cả lúc có sự cố lẫn lúc bình thường.
- **Sửa định nghĩa SLI.** Đo từ `CorrelationIdMiddleware` (lúc request vào cổng)
  thay vì từ trong `agent.run()`, để con số trên dashboard là con số người dùng
  cảm nhận. Nếu không sửa, mọi alert latency đều mù với hàng đợi.
- **Thêm alert theo span, không chỉ theo request.** `retrieval` P95 > 300 ms là
  alert bắt được đúng sự cố này sớm hơn alert latency end-to-end, và chỉ thẳng
  vào span nghi vấn thay vì chỉ nói "chậm".
- **Alert 1 và 2 không thay thế được nhau.** Ở sự cố này `error_rate` = 0 % và
  `retrieval success` = 100 %, nên alert 2 im lặng hoàn toàn; chỉ alert 1
  (`p95 > 3000 ms`) kêu. Nếu bài chỉ có alert theo lỗi thì sự cố đã không được
  phát hiện.
- **Cảnh báo về dữ liệu thưa.** Với 5 request trong một phút, "P95" thực chất chỉ
  là giá trị lớn nhất. Kết luận ở đây vẫn đứng vững vì nó được xác nhận độc lập
  bằng duration của span, không chỉ bằng percentile.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** đặt `@observe` **tại nơi phát
  sinh dữ liệu** (`retrieve()` trong `mock_rag.py`, `FakeLLM.generate()` trong
  `mock_llm.py`) thay vì bọc trong `agent.py`. Lý do trực tiếp là ràng buộc của
  `tests/test_agent_prompt_trace.py` (mục 5.1), nhưng lý do thiết kế mới là
  chính: mỗi thành phần tự khai báo observation của mình thì `agent.py` chỉ còn
  lo điều phối, và thêm một bước mới vào pipeline (ví dụ re-ranker) sẽ tự động
  có span mà không phải sửa orchestrator. Đây đúng là điều mà luồng
  Metrics → Logs → Traces cần: tầng nào biết dữ liệu thì tầng đó công bố.

- **Một lỗi/blocker đã gặp:** `GET /api/public/traces` trả
  `410 LEGACY_API_UNAVAILABLE_FOR_NEW_ORGANIZATION`, chặn hoàn toàn việc kiểm
  đếm trace bằng script. Ban đầu tôi tưởng là lỗi key hoặc sai project.

- **Cách tìm nguyên nhân và xử lý:** đọc kỹ mã lỗi — `410 Gone` kèm
  `FOR_NEW_ORGANIZATION` nghĩa là endpoint cũ đã bị khai tử riêng cho tổ chức
  mới, không phải lỗi xác thực. Chuyển sang
  `client.api.observations.get_many(from_start_time=..., to_start_time=..., fields=...)`.
  Một chi tiết phụ tốn thêm thời gian: các field `model`, `usage`, `prompt` chỉ
  được trả về khi **yêu cầu tường minh** qua tham số `fields`, mặc định chúng
  rỗng — nên lần đầu tôi tưởng generation không ghi được model/cost.

- **Cách hiểu luồng Metrics → Logs → Traces:** mỗi lớp trả lời một câu hỏi khác
  nhau, và thứ tự này không đảo được. **Metrics** cho biết *cái gì* hỏng và *từ
  lúc nào* — nhưng chỉ ở mức tổng hợp, không chỉ ra request nào. **Logs** thu hẹp
  từ "khoảng thời gian" xuống "một request cụ thể" qua `correlation_id`, cho biết
  *chuyện gì* đã xảy ra. **Traces** trả lời *tại sao* — waterfall chỉ ra span nào
  gánh thời gian. Khoá nối ba lớp là `correlation_id`, và nếu khoá đó đứt thì đó
  là lỗi observability cần sửa trước, không phải lỗi hệ thống cần điều tra.

- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành
  LLM:** prompt là **mã nguồn chạy trên production nhưng không nằm trong git**,
  nên version hoá nó là cách duy nhất để trả lời "câu trả lời hôm qua khác hôm
  nay vì đâu". Label `production`/`candidate`/`baseline` biến việc đổi hành vi
  model thành một thao tác **có thể rollback trong một dòng lệnh** thay vì một
  lần deploy. Token và cost là mặt chi phí của cùng hành vi đó — prompt v2 yêu
  cầu trả lời ngắn hơn, tức vừa đổi chất lượng vừa đổi hoá đơn, nên hai thứ phải
  được đo cạnh nhau. SLO biến "hệ thống chạy được" thành một con số có thể vi
  phạm, và error budget biến việc vi phạm đó thành quyết định kinh doanh: còn
  ngân sách thì tiếp tục deploy, hết ngân sách thì đóng băng.

- **Điều quan trọng nhất đã học:** một dashboard vẽ ra được **chưa chắc đã đúng**.
  Lỗi "phút rỗng vẽ thành 0" ở mục 6.1 tạo ra biểu đồ P99 tụt về 0 ms trông y hệt
  một sự cố thật. Không có validator nào bắt được lỗi đó — chỉ có việc render ra
  và nhìn mới thấy. Bài học: trong observability, **dữ liệu sai nguy hiểm hơn
  thiếu dữ liệu**, vì thiếu thì biết là thiếu, còn sai thì vẫn ra quyết định.

- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**
  - Cửa sổ quan sát còn nhỏ (90 request) nên các percentile theo phút chỉ mang
    tính minh hoạ; p95 của vài mẫu thực chất chỉ là giá trị lớn nhất. Muốn alert
    latency đáng tin phải có lưu lượng thật.
  - `tool_success` trong `app/main.py` vẫn hard-code `True`, nên panel *retrieval
    success* trong điều kiện bình thường luôn bằng 100% và **không phản ánh chất
    lượng truy hồi thật**. Nó chỉ thực sự có tác dụng khi retrieval ném lỗi
    (`tool_fail`). Đây là chỗ cần sửa trước khi dùng dashboard để trực thật.
  - Cost trong bài là cost ước lượng từ bảng giá giả lập, không phải hoá đơn thật.
  - Dashboard là ảnh chụp tại thời điểm render (`dashboard.html` sinh một lần),
    chưa có cơ chế tự refresh mỗi 15–30 giây như `refresh_seconds` trong
    `config/dashboard.yaml` khai báo; hiện phải chạy lại script để cập nhật.

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
