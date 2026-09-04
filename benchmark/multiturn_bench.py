"""
Multi-turn KV-cache routing benchmark.

Simulates several independent, concurrent multi-turn conversations against a
vLLM-compatible OpenAI API endpoint, and records the Time-To-First-Token (TTFT)
for each turn separately. Turn 1 of any conversation has no prior cache to hit
or miss (not informative). Turn 2+ TTFT is the signal we care about: a router
that sends a conversation's turns back to the same replica should show
consistently low turn-2+ TTFT, while a round-robin/blind router should show
turn-2+ TTFT roughly halfway between a cache-hit and cache-miss latency
(since with 2 replicas it has ~50% odds of accidentally landing on the right
one, and no way to do better than chance).

Usage:
    python multiturn_bench.py --url http://localhost:8000 --model meta-llama/Llama-3.2-3B-Instruct --out baseline_multiturn.json
"""

import argparse
import asyncio
import json
import os
import time

import httpx

CONVERSATIONS_PATH = os.path.join(os.path.dirname(__file__), "real_conversations.json")
with open(CONVERSATIONS_PATH) as f:
    CONVERSATIONS = json.load(f)


async def send_turn(client: httpx.AsyncClient, url: str, model: str, messages: list[dict]) -> tuple[float, str]:
    """Send one chat turn with streaming enabled; return (ttft_seconds, assistant_reply_text)."""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 400,
        "stream": True,
    }
    start = time.monotonic()
    ttft = None
    reply_chunks = []

    async with client.stream("POST", f"{url}/v1/chat/completions", json=payload, timeout=120.0) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            delta = chunk["choices"][0]["delta"].get("content")
            if delta:
                if ttft is None:
                    ttft = time.monotonic() - start
                reply_chunks.append(delta)

    return ttft, "".join(reply_chunks)


async def run_conversation(client: httpx.AsyncClient, url: str, model: str, conv_id: int, turns: list[str], results: list[dict]):
    messages = []
    for turn_num, user_text in enumerate(turns, start=1):
        messages.append({"role": "user", "content": user_text})
        ttft, reply = await send_turn(client, url, model, messages)
        messages.append({"role": "assistant", "content": reply})
        results.append({"conversation_id": conv_id, "turn": turn_num, "ttft_seconds": ttft})
        print(f"[conv {conv_id}] turn {turn_num}: TTFT = {ttft:.3f}s")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Base URL of the server, e.g. http://localhost:8000")
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True, help="Path to write raw results JSON")
    parser.add_argument("--repeats", type=int, default=3, help="How many times to repeat the full concurrent batch")
    args = parser.parse_args()

    all_results = []
    async with httpx.AsyncClient() as client:
        for r in range(args.repeats):
            print(f"\n=== Batch {r + 1}/{args.repeats}: launching {len(CONVERSATIONS)} concurrent conversations ===")
            batch_results = []
            await asyncio.gather(*[
                run_conversation(client, args.url, args.model, conv_id, turns, batch_results)
                for conv_id, turns in enumerate(CONVERSATIONS)
            ])
            all_results.extend(batch_results)

    with open(args.out, "w") as f:
        json.dump(all_results, f, indent=2)

    turn1 = [r["ttft_seconds"] for r in all_results if r["turn"] == 1]
    followups = [r["ttft_seconds"] for r in all_results if r["turn"] > 1]
    print(f"\nWrote {len(all_results)} results to {args.out}")
    print(f"Turn 1 avg TTFT:      {sum(turn1) / len(turn1):.3f}s  (n={len(turn1)})")
    print(f"Turn 2+ avg TTFT:     {sum(followups) / len(followups):.3f}s  (n={len(followups)})")


if __name__ == "__main__":
    asyncio.run(main())
