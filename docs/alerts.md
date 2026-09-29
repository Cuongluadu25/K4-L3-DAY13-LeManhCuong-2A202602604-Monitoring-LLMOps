# Alert và Runbook

Ba alert dưới đây đều **symptom-based**: chúng mô tả cái người dùng cảm nhận
được (chờ lâu, nhận lỗi, câu trả lời sai ngữ cảnh, hoá đơn tăng), không mô tả
tên hàm hay hàng đợi nội bộ. Nhờ vậy alert vẫn còn đúng khi ta refactor code.

Cấu hình máy đọc được nằm ở [config/alert_rules.yaml](../config/alert_rules.yaml);
ngưỡng SLO và error budget nằm ở [config/slo.yaml](../config/slo.yaml).

## Luồng điều tra chung: Metrics → Logs → Traces

Mọi alert đều đi theo cùng một đường, vì mỗi lớp trả lời một câu khác nhau:

1. **Metrics (dashboard 6 panel)** — *Cái gì* đang hỏng và từ lúc nào.
   Xác định panel bất thường và khoảng thời gian.
2. **Logs (`data/logs.jsonl`)** — *Chuyện gì* đã xảy ra với từng request.
   Lọc theo khoảng thời gian trên, tìm một `correlation_id` của request bất
   thường. Log đã được enrich `user_id_hash`, `session_id`, `feature`, `model`,
   `env` và đã che PII.
3. **Traces (Langfuse)** — *Tại sao* chậm/lỗi. Tìm trace có cùng
   `correlation_id`, mở waterfall để biết span nào gánh thời gian: `retrieval`
   (truy hồi tài liệu) hay `fake-llm-generation` (sinh câu trả lời).

> Ghi nhớ: ba lớp phải nối được với nhau bằng `correlation_id`. Nếu không nối
> được thì đó là lỗi observability, không phải lỗi hệ thống.

---

## Alert 1

- **Tên:** `chat_latency_p95_high`
- **Severity:** critical (page on-call)
- **Duration:** 5 phút
- **Kênh thông báo:** Slack `#alerts-oncall`
- **SLI/SLO liên quan:** `primary_slo.fast_successful_requests` —
  99,5% request phải có `latency_ms <= 3000` trong 28 ngày.
- **Điều kiện và thời gian duy trì:**
  `p95(response_sent.latency_ms, 5m) > 3000` duy trì liên tục 5 phút.
- **Ảnh hưởng tới người dùng:** người dùng chờ câu trả lời quá 3 giây. Với chat
  tương tác, quá ~3 giây được coi là "treo"; người dùng sẽ bỏ đi hoặc gửi lại
  request, làm tăng tải và tăng chi phí.
- **Ba bước kiểm tra đầu tiên:**
  1. Mở dashboard, xem panel *1. Latency percentiles và TTFT*. Xác định P95 tăng
     ở **latency end-to-end** hay ở **TTFT**. TTFT tăng ⇒ vấn đề ở phía sinh
     token; chỉ latency tăng mà TTFT phẳng ⇒ vấn đề nằm trước đó (truy hồi).
  2. Lọc `data/logs.jsonl` theo khoảng thời gian đó, lấy một `correlation_id`
     của request có `latency_ms` lớn.
  3. Vào Langfuse, tìm trace theo `correlation_id`, mở waterfall: span
     `retrieval` hay `fake-llm-generation` chiếm phần lớn thời gian?
- **Mitigation tạm thời:**
  - Nếu `retrieval` chậm (thường gặp khi bật incident `rag_slow`): tạm giảm
    `top_k`/bỏ bước re-rank, hoặc trả lời từ cache cho câu hỏi phổ biến.
  - Nếu `generation` chậm: hạ `max_tokens`, hoặc chuyển sang model nhỏ hơn.
  - Nếu do một request đơn lẻ (outlier) trong khi P50 vẫn thấp: đặt timeout cho
    retrieval để không kéo dài đuôi phân bố.
- **Owner:** on-call LLMOps
- **Runbook:** mục này (`docs/alerts.md#alert-1`)

> **Lưu ý về mẫu nhỏ:** p95 chỉ có ý nghĩa khi cửa sổ có đủ request. Trên
> baseline 2026-09-29, alert này **có kêu** (p95 5 phút = 3449 ms lúc 08:06) và
> kêu đúng: chính request đó đã vượt error budget. Nhưng khi lưu lượng còn thấp,
> hãy kiểm tra số request trong cửa sổ trước khi kết luận — p95 của 2–3 mẫu chỉ
> đơn thuần là giá trị lớn nhất.

---

## Alert 2

- **Tên:** `chat_failure_and_retrieval_degraded`
- **Severity:** critical (page on-call)
- **Duration:** 2 phút
- **Kênh thông báo:** Slack `#alerts-critical`
- **SLI/SLO liên quan:** guardrail `error_rate_pct_max: 2` và
  `retrieval_success_rate_pct_min: 90`.
- **Điều kiện và thời gian duy trì:**
  `error_rate_pct > 2` trong 2 phút, **hoặc** `tool_success_rate_pct < 90`
  trong 3 phút.
- **Ảnh hưởng tới người dùng:** hai triệu chứng khác nhau nhưng cùng một nhóm
  nguyên nhân:
  - `error_rate` tăng ⇒ người dùng nhận lỗi HTTP, không có câu trả lời.
  - `tool_success` giảm ⇒ request vẫn trả 200 nhưng **câu trả lời không dựa
    trên tài liệu** (retrieval thất bại, agent rơi vào câu trả lời chung).
    Đây là kiểu hỏng nguy hiểm hơn vì im lặng — người dùng không biết là sai.
- **Ba bước kiểm tra đầu tiên:**
  1. Xem panel *3. Error rate và retrieval success*: bên nào bất thường? Đồng
     thời mở *Breakdown lỗi* để biết `error_type` nào đang chiếm ưu thế.
  2. Lọc `data/logs.jsonl` tìm event `request_failed` trong khoảng đó, lấy
     `correlation_id` và `error_type`.
  3. Mở trace tương ứng trong Langfuse. Với `tool_fail`, span `retrieval` sẽ
     mang trạng thái lỗi — xác nhận đúng span gây ra vấn đề.
- **Mitigation tạm thời:**
  - Nếu là `tool_fail` (vector store timeout): bật lại câu trả lời fallback có
    ghi rõ "không truy được tài liệu", tạm tắt re-rank, hoặc chuyển sang index
    dự phòng.
  - Nếu là lỗi upstream/model: bật retry có backoff rồi trả lỗi mềm cho người
    dùng thay vì treo.
  - Kiểm tra ngay ngân sách lỗi còn lại ở `config/slo.yaml` để quyết định có
    cần đóng băng deploy hay không.
- **Owner:** on-call LLMOps
- **Runbook:** mục này (`docs/alerts.md#alert-2`)

---

## Alert 3

- **Tên:** `llm_cost_burn_high`
- **Severity:** warning (không page, gửi Slack)
- **Duration:** 10 phút
- **Kênh thông báo:** Slack `#alerts-cost`
- **SLI/SLO liên quan:** guardrail `daily_cost_usd_max: 2.5`.
- **Điều kiện và thời gian duy trì:**
  `sum(response_sent.cost_usd, 10m) > 0.35` USD duy trì 10 phút — tương đương
  tốc độ > 2,1 USD/giờ, đủ để vượt trần 2,5 USD/ngày nếu kéo dài.
- **Ảnh hưởng tới người dùng:** trực tiếp thì người dùng chưa thấy gì, nhưng
  đây là alert **warning có chủ đích**: chi phí tăng vọt thường là dấu hiệu sớm
  của lỗi hệ thống (retry storm, prompt phình to, retrieval trả quá nhiều
  document) và sẽ dẫn tới việc phải cắt dịch vụ nếu không xử lý.
- **Ba bước kiểm tra đầu tiên:**
  1. Xem panel *4. Cost tích luỹ trong cửa sổ* và *5. Input/output tokens tích
     luỹ*. Chi phí tăng do **token vào** (prompt/context phình) hay do **token
     ra** (model trả lời dài)?
  2. Đối chiếu panel *2. Request traffic*: chi phí tăng vì **nhiều request hơn**
     (hợp lý) hay vì **mỗi request đắt hơn** (bất thường)?
  3. Lấy vài `correlation_id` trong khoảng đó, mở trace, so `usage` và `cost`
     của span `fake-llm-generation` với mức thường ngày.
- **Mitigation tạm thời:**
  - Nếu do context phình: giảm số document trả về từ retrieval, cắt bớt lịch sử
    hội thoại đưa vào prompt.
  - Nếu do output dài: hạ `max_tokens`, hoặc dùng prompt version yêu cầu trả lời
    ngắn gọn (chính là thay đổi của prompt v2 — xem `docs/PROMPT_VERSIONING.md`).
  - Nếu do retry storm: tạm chặn retry và xử lý lỗi gốc trước.
  - Nếu là tăng trưởng thật: cập nhật lại guardrail `daily_cost_usd_max` **có
    chủ đích**, kèm ghi chú lý do, thay vì để alert kêu mãi.
- **Owner:** LLMOps owner
- **Runbook:** mục này (`docs/alerts.md#alert-3`)

---

## Quan hệ giữa ba alert

| Alert | Triệu chứng | Guardrail / SLO | Xử lý khi nào |
|---|---|---|---|
| 1 | Chờ quá lâu | `fast_successful_requests` (99,5% ≤ 3000 ms) | Page ngay |
| 2 | Nhận lỗi / trả lời sai ngữ cảnh | `error_rate_pct_max`, `retrieval_success_rate_pct_min` | Page ngay |
| 3 | Hoá đơn tăng bất thường | `daily_cost_usd_max` | Slack, xử lý trong giờ |

Alert 2 được cấu hình **inhibit** alert 1: khi request đang lỗi hàng loạt thì
latency P95 thường tăng theo, gây nhiễu. Chặn alert 1 trong trường hợp đó giúp
on-call tập trung vào nguyên nhân gốc. Cấu hình nằm ở mục `defaults.inhibit`
trong `config/alert_rules.yaml`.
