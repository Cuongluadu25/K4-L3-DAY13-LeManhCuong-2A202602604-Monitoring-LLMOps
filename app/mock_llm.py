from __future__ import annotations

import random
import time
from dataclasses import dataclass

from .incidents import STATE
from .pii import summarize_text
from .tracing import get_langfuse_client, observe

# Bảng giá ước tính (USD cho 1 triệu token). Dùng chung với LabAgent._estimate_cost.
INPUT_PRICE_PER_MILLION = 3.0
OUTPUT_PRICE_PER_MILLION = 15.0


def estimate_cost(tokens_in: int, tokens_out: int) -> float:
    input_cost = (tokens_in / 1_000_000) * INPUT_PRICE_PER_MILLION
    output_cost = (tokens_out / 1_000_000) * OUTPUT_PRICE_PER_MILLION
    return round(input_cost + output_cost, 6)


@dataclass
class FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class FakeResponse:
    text: str
    usage: FakeUsage
    model: str
    ttft_ms: int


class FakeLLM:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model

    @observe(
        name="fake-llm-generation",
        as_type="generation",
        capture_input=False,
        capture_output=False,
    )
    def generate(self, prompt: str) -> FakeResponse:
        started = time.perf_counter()
        time.sleep(0.05)  # mô phỏng thời điểm token đầu tiên sẵn sàng
        ttft_ms = int((time.perf_counter() - started) * 1000)
        time.sleep(0.10)
        input_tokens = max(20, len(prompt) // 4)
        output_tokens = random.randint(80, 180)
        if STATE["cost_spike"]:
            output_tokens *= 4
        answer = (
            "Starter answer. You should improve this output logic and add better quality checks. "
            "Use retrieved context and keep responses concise."
        )
        response = FakeResponse(
            text=answer,
            usage=FakeUsage(input_tokens, output_tokens),
            model=self.model,
            ttft_ms=ttft_ms,
        )
        self._record_generation(response, prompt)
        return response

    def _record_generation(self, response: FakeResponse, prompt: str) -> None:
        """Gắn input/output đã scrub, model, usage và cost vào generation.

        capture_input/capture_output đã tắt ở decorator nên prompt thô không bị
        SDK tự ghi; ở đây chỉ gửi bản preview đã scrub PII và cắt ngắn.
        """
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        get_langfuse_client().update_current_generation(
            input={"prompt_preview": summarize_text(prompt)},
            output={"answer_preview": summarize_text(response.text)},
            model=self.model,
            usage_details={
                "input": tokens_in,
                "output": tokens_out,
                "total": tokens_in + tokens_out,
            },
            cost_details={"total": estimate_cost(tokens_in, tokens_out)},
            metadata={"ttft_ms": response.ttft_ms},
        )
