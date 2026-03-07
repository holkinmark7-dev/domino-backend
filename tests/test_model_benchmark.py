# tests/test_model_benchmark.py
"""
Real API benchmark — calls each provider/model once and reports latency.
Run:  python -m pytest tests/test_model_benchmark.py -v -s -m benchmark
"""
import os
import time

import pytest

from routers.services.model_router import MODELS

# Skip entire module if any API key is missing
REQUIRED_KEYS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"}
missing = [k for k in REQUIRED_KEYS if not os.getenv(k)]
pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.skipif(bool(missing), reason=f"Missing env vars: {missing}"),
]

PROMPT_SYSTEM = "You are a helpful assistant. Reply in one short sentence."
PROMPT_USER = "What is 2+2?"


def _call_openai(model: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=model,
        max_tokens=50,
        messages=[
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": PROMPT_USER},
        ],
    )
    return resp.choices[0].message.content


def _call_anthropic(model: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=model,
        max_tokens=50,
        system=PROMPT_SYSTEM,
        messages=[{"role": "user", "content": PROMPT_USER}],
    )
    return resp.content[0].text


def _call_google(model: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    gen_model = genai.GenerativeModel(model, system_instruction=PROMPT_SYSTEM)
    resp = gen_model.generate_content(PROMPT_USER)
    return resp.text


BENCHMARK_CASES = [
    ("gemini_flash", _call_google),
    ("haiku", _call_anthropic),
    ("sonnet", _call_anthropic),
    ("gpt4o_mini", _call_openai),
    ("gpt4o", _call_openai),
]


@pytest.mark.parametrize("model_key,call_fn", BENCHMARK_CASES, ids=[c[0] for c in BENCHMARK_CASES])
def test_model_responds(model_key, call_fn):
    """Call each model with a trivial prompt and verify it responds."""
    config = MODELS[model_key]
    t0 = time.perf_counter()
    try:
        text = call_fn(config.model)
    except Exception as exc:
        if "quota" in str(exc).lower() or "rate" in str(exc).lower():
            pytest.skip(f"{model_key}: quota/rate limit exceeded")
        raise
    elapsed = time.perf_counter() - t0

    assert text and len(text) > 0, f"{model_key} returned empty response"
    print(f"\n  {model_key:15s} | {config.model:30s} | {elapsed:.2f}s | {text.strip()[:60]}")
