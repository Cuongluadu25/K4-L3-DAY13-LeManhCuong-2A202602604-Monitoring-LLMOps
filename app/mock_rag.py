from __future__ import annotations

import time

from .incidents import STATE
from .pii import summarize_text
from .tracing import get_langfuse_client, observe

CORPUS = {
    "refund": ["Refunds are available within 7 days with proof of purchase."],
    "monitoring": ["Metrics detect incidents, logs identify affected requests, traces localize the root cause."],
    "policy": ["Do not expose PII in logs. Use sanitized summaries only."],
}


@observe(
    name="retrieval",
    as_type="retriever",
    capture_input=False,
    capture_output=False,
)
def retrieve(message: str) -> list[str]:
    if STATE["tool_fail"]:
        raise RuntimeError("Vector store timeout")
    if STATE["rag_slow"]:
        time.sleep(2.5)
    lowered = message.lower()
    docs: list[str] = ["No domain document matched. Use general fallback answer."]
    for key, entries in CORPUS.items():
        if key in lowered:
            docs = entries
            break
    # capture_input/capture_output đã tắt ở decorator nên SDK KHÔNG tự ghi tham
    # số thô. Ta chủ động ghi bản preview đã scrub PII và cắt ngắn, nhờ vậy span
    # vẫn đọc được trong waterfall mà không đưa dữ liệu thô lên Langfuse.
    get_langfuse_client().update_current_span(
        input={"query_preview": summarize_text(message)},
        output={
            "doc_count": len(docs),
            "doc_previews": [summarize_text(doc) for doc in docs],
        },
        metadata={"doc_count": len(docs)},
    )
    return docs
