"""Quick LM Studio latency benchmark (stream + complete, multiple hosts)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
VR = ROOT / "packages" / "voice-runtime"
sys.path.insert(0, str(VR))

MODEL = "qwen3-3b"
USER = "That's pretty cool"
BASES = [
    ("10.16.12.1", "http://10.16.12.1:1234/v1"),
    ("127.0.0.1", "http://127.0.0.1:1234/v1"),
]
EXTRA = {
    "extra_body": {
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
    }
}


def ping_models(client: OpenAI, timeout: float = 15.0) -> dict:
    t0 = time.perf_counter()
    try:
        client.models.list(timeout=timeout)
        return {"ok": True, "ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "ms": round((time.perf_counter() - t0) * 1000), "error": str(exc)[:160]}


def bench_stream(client: OpenAI, messages: list[dict], *, max_tokens: int = 120) -> dict:
    t0 = time.perf_counter()
    ttft = None
    chunks: list[str] = []
    try:
        stream = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            stream=True,
            temperature=0.6,
            max_tokens=max_tokens,
            timeout=30.0,
            **EXTRA,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if delta:
                if ttft is None:
                    ttft = time.perf_counter() - t0
                chunks.append(delta)
        total = time.perf_counter() - t0
        return {
            "ok": True,
            "ttft_ms": round((ttft or total) * 1000),
            "total_ms": round(total * 1000),
            "chars": len("".join(chunks)),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "total_ms": round((time.perf_counter() - t0) * 1000), "error": str(exc)[:160]}


def bench_complete(client: OpenAI, messages: list[dict], *, tools: list[dict] | None = None) -> dict:
    t0 = time.perf_counter()
    kwargs: dict = dict(
        model=MODEL,
        messages=messages,
        stream=False,
        temperature=0.6,
        max_tokens=220,
        timeout=45.0,
        **EXTRA,
    )
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    try:
        resp = client.chat.completions.create(**kwargs)
        total = time.perf_counter() - t0
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        return {
            "ok": True,
            "total_ms": round(total * 1000),
            "chars": len(msg.content or ""),
            "tool_calls": len(tool_calls),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "total_ms": round((time.perf_counter() - t0) * 1000), "error": str(exc)[:160]}


def load_agent_context() -> tuple[list[dict], list[dict], str]:
    """Build messages + tool schema like a real voice turn."""
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "packages" / "voice-runtime"))

    from services.settings.store import apply_to_config, load_settings

    apply_to_config(load_settings())
    from config import CONFIG
    from agent import VoiceAgent

    agent = VoiceAgent("vad")
    agent.start_session(mic_source="browser")
    t0 = time.perf_counter()
    messages = agent._build_messages(USER)
    build_ms = round((time.perf_counter() - t0) * 1000)
    tools = agent.registry.openai_schema() if agent.registry else []
    base = CONFIG.llm.base_url
    sys_len = sum(len(m.get("content") or "") for m in messages if m.get("role") == "system")
    tools_json = len(json.dumps(tools))
    print(
        f"  agent context: base_url={base} build_ms={build_ms} "
        f"system_chars={sys_len} tools={len(tools)} tools_json_chars={tools_json} messages={len(messages)}"
    )
    return messages, tools, base


def main() -> None:
    simple = [
        {"role": "system", "content": "You are Maya. Reply in 1-2 short spoken sentences."},
        {"role": "user", "content": USER},
    ]

    print("Loading agent-sized prompt from settings...")
    agent_messages: list[dict] = []
    agent_tools: list[dict] = []
    configured_base = ""
    try:
        agent_messages, agent_tools, configured_base = load_agent_context()
        print(f"  settings base_url: {configured_base}")
    except Exception as exc:  # noqa: BLE001
        print(f"agent context load failed: {exc}")

    for label, base in BASES:
        print(f"\n=== {label} ({base}) ===")
        client = OpenAI(base_url=base, api_key="lm-studio")
        print(f"  models: {ping_models(client)}")
        print(f"  stream simple: {bench_stream(client, simple)}")
        print(f"  complete simple: {bench_complete(client, simple)}")
        if agent_messages:
            print(f"  complete agent-msgs: {bench_complete(client, agent_messages)}")
            if agent_tools:
                print(f"  complete agent+tools: {bench_complete(client, agent_messages, tools=agent_tools)}")


if __name__ == "__main__":
    main()
