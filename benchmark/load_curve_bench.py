"""
Load-curve benchmark: sweep across concurrency levels, sending that many
single-turn requests simultaneously at each level, to see how TTFT and
throughput degrade as contention increases. This is the disaggregation-
relevant benchmark (prefill/decode contention under concurrent mixed-length
load) as opposed to multiturn_bench.py's cache-routing-relevant benchmark.

Usage:
    python load_curve_bench.py --url http://vllm-baseline:8000 --model meta-llama/Llama-3.2-3B-Instruct --out baseline_load_curve.json
"""

import argparse
import asyncio
import json
import time

import httpx

PROMPTS_PATH = __file__.rsplit("/", 1)[0] + "/load_curve_prompts.json"
with open(PROMPTS_PATH) as f:
    PROMPTS = json.load(f)

CONCURRENCY_LEVELS = [1, 4, 8, 16, 32, 64]
REPEATS_PER_LEVEL = 2
MAX_TOKENS = 200


async def send_request(client: httpx.AsyncClient, url: str, model: str, prompt: str) -> dict:
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": MAX_TOKENS,
        "stream": True,
    }
    start = time.monotonic()
    ttft = None
    completion_tokens = 0

    async with client.stream("POST", f"{url}/v1/completions", json=payload, timeout=120.0) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            text = chunk["choices"][0].get("text", "")
            if text:
                if ttft is None:
                    ttft = time.monotonic() - start
                completion_tokens += 1  # approximate: one chunk ~= one token for vLLM streaming

    total_latency = time.monotonic() - start
    return {"ttft": ttft, "total_latency": total_latency, "completion_tokens": completion_tokens}


def percentile(values: list[float], p: float) -> float:
    s = sorted(values)
    idx = int(len(s) * p)
    return s[min(idx, len(s) - 1)]


async def run_concurrency_level(client: httpx.AsyncClient, url: str, model: str, concurrency: int) -> dict:
    prompts = [PROMPTS[i % len(PROMPTS)] for i in range(concurrency)]
    batch_start = time.monotonic()
    results = await asyncio.gather(*[send_request(client, url, model, p) for p in prompts])
    wall_time = time.monotonic() - batch_start

    ttfts = [r["ttft"] for r in results if r["ttft"] is not None]
    total_tokens = sum(r["completion_tokens"] for r in results)

    return {
        "concurrency": concurrency,
        "wall_time_seconds": wall_time,
        "avg_ttft": sum(ttfts) / len(ttfts),
        "p50_ttft": percentile(ttfts, 0.5),
        "p90_ttft": percentile(ttfts, 0.9),
        "throughput_tokens_per_sec": total_tokens / wall_time,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    all_results = []
    async with httpx.AsyncClient() as client:
        for concurrency in CONCURRENCY_LEVELS:
            for rep in range(REPEATS_PER_LEVEL):
                print(f"=== Concurrency {concurrency}, repeat {rep + 1}/{REPEATS_PER_LEVEL} ===")
                stats = await run_concurrency_level(client, args.url, args.model, concurrency)
                print(f"  avg TTFT={stats['avg_ttft']:.3f}s  p50={stats['p50_ttft']:.3f}s  "
                      f"p90={stats['p90_ttft']:.3f}s  throughput={stats['throughput_tokens_per_sec']:.1f} tok/s")
                all_results.append(stats)

    with open(args.out, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nWrote {len(all_results)} data points to {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
