"""
Render benchmark/baseline_load_curve.json as a two-panel PNG chart:
TTFT (avg/p50/p90) vs concurrency, and throughput vs concurrency.
"""

import json
import os

import matplotlib.pyplot as plt

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "baseline_load_curve.json")) as f:
    raw = json.load(f)

# average the 2 repeats per concurrency level
by_concurrency = {}
for r in raw:
    by_concurrency.setdefault(r["concurrency"], []).append(r)

concurrencies = sorted(by_concurrency.keys())
avg_ttft = [sum(r["avg_ttft"] for r in by_concurrency[c]) / len(by_concurrency[c]) * 1000 for c in concurrencies]
p50_ttft = [sum(r["p50_ttft"] for r in by_concurrency[c]) / len(by_concurrency[c]) * 1000 for c in concurrencies]
p90_ttft = [sum(r["p90_ttft"] for r in by_concurrency[c]) / len(by_concurrency[c]) * 1000 for c in concurrencies]
throughput = [sum(r["throughput_tokens_per_sec"] for r in by_concurrency[c]) / len(by_concurrency[c]) for c in concurrencies]

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
fig.suptitle("Baseline Load Curve — plain vLLM, 2 replicas, round-robin", fontsize=13, fontweight="bold")

ax1.plot(concurrencies, avg_ttft, marker="o", color=BLUE, label="avg", linewidth=2)
ax1.plot(concurrencies, p50_ttft, marker="o", color=ORANGE, label="p50", linewidth=2)
ax1.plot(concurrencies, p90_ttft, marker="o", color=AQUA, label="p90", linewidth=2)
ax1.set_xscale("log", base=2)
ax1.set_xticks(concurrencies)
ax1.set_xticklabels(concurrencies)
ax1.set_xlabel("concurrent requests")
ax1.set_ylabel("TTFT (ms)")
ax1.set_title("Time-to-first-token vs. concurrency")
ax1.legend(frameon=False)
ax1.grid(True, alpha=0.3)
ax1.spines["top"].set_visible(False)
ax1.spines["right"].set_visible(False)

ax2.plot(concurrencies, throughput, marker="o", color=BLUE, linewidth=2)
ax2.set_xscale("log", base=2)
ax2.set_xticks(concurrencies)
ax2.set_xticklabels(concurrencies)
ax2.set_xlabel("concurrent requests")
ax2.set_ylabel("throughput (tokens/sec)")
ax2.set_title("Throughput vs. concurrency")
ax2.grid(True, alpha=0.3)
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_visible(False)

fig.tight_layout(rect=[0, 0, 1, 0.94])
out_path = os.path.join(HERE, "baseline_load_curve.png")
fig.savefig(out_path, dpi=150)
print(f"Wrote {out_path}")
