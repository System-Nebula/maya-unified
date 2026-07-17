"""One-shot: tool-loop shaped complete() via the live LLM client factory."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "voice-runtime"))

from agent import VoiceAgent
from services.llm.provider import create_llm_client, get_provider_name
from services.settings.store import apply_to_config, load_settings

USER = "That's pretty cool"

apply_to_config(load_settings())
print("provider", get_provider_name())
client = create_llm_client()
print("client", type(client).__name__, "model", client.cfg.model, "base", client.cfg.base_url)

agent = VoiceAgent("vad")
agent.llm = client
agent.start_session(mic_source="browser")
msgs = agent._build_messages(USER)
tools = agent.registry.openai_schema() if agent.registry else []
print("messages", len(msgs), "tools", len(tools))

t0 = time.perf_counter()
resp = client.complete(msgs, tools=tools or None)
ms = round((time.perf_counter() - t0) * 1000)
print("complete_ms", ms)
print("chars", len(resp.content or ""), "tool_calls", len(resp.tool_calls))
print("preview", (resp.content or "")[:160])
