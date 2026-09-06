"""
Baseline vs. llm-d comparison charts: load curve (TTFT + throughput vs
concurrency) and multi-turn TTFT distribution (turn 1 vs turn 2+).
"""

import json
import os
import statistics as stats

import matplotlib.pyplot as plt

HERE = os.path.dirname(__file__)
BLUE, ORANGE = "#2a78d6", "#eb6834"


def load_curve_by_concurrency(path):
    with open(os.path.join(HERE, path)) as f:
        raw = json.load(f)
    by_c = {}
    for r in raw:
        by_c.setdefault(r["concurrency"], []).append(r)
    cs = sorted(by_c.keys())
    avg_ttft = [sum(r["avg_ttft"] for r in by_c[c]) / len(by_c[c]) * 1000 for c in cs]
    tput = [sum(r["throughput_tokens_per_sec"] for r in by_c[c]) / len(by_c[c]) for c in cs]
    return cs, avg_ttft, tput


# --- Load curve comparison ---
cs, b_ttft, b_tput = load_curve_by_concurrency("baseline_load_curve.json")
_, l_ttft, l_tput = load_curve_by_concurrency("llmd_load_curve.json")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
fig.suptitle("Baseline vs. llm-d — Load Curve", fontsize=13, fontweight="bold")

ax1.plot(cs, b_ttft, marker="o", color=BLUE, label="baseline", linewidth=2)
ax1.plot(cs, l_ttft, marker="o", color=ORANGE, label="llm-d (P/D disaggregated)", linewidth=2)
ax1.set_xscale("log", base=2)
ax1.set_xticks(cs)
ax1.set_xticklabels(cs)
ax1.set_xlabel("concurrent requests")
ax1.set_ylabel("avg TTFT (ms)")
ax1.set_title("TTFT vs. concurrency")
ax1.legend(frameon=False)
ax1.grid(True, alpha=0.3)
ax1.spines["top"].set_visible(False)
ax1.spines["right"].set_visible(False)

ax2.plot(cs, b_tput, marker="o", color=BLUE, label="baseline", linewidth=2)
ax2.plot(cs, l_tput, marker="o", color=ORANGE, label="llm-d (P/D disaggregated)", linewidth=2)
ax2.set_xscale("log", base=2)
ax2.set_xticks(cs)
ax2.set_xticklabels(cs)
ax2.set_xlabel("concurrent requests")
ax2.set_ylabel("throughput (tokens/sec)")
ax2.set_title("Throughput vs. concurrency")
ax2.legend(frameon=False)
ax2.grid(True, alpha=0.3)
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_visible(False)

fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig(os.path.join(HERE, "comparison_load_curve.png"), dpi=150)
print("Wrote comparison_load_curve.png")


# --- Multi-turn comparison ---
def turn_values(path):
    with open(os.path.join(HERE, path)) as f:
        data = json.load(f)
    t1 = [d["ttft_seconds"] * 1000 for d in data if d["turn"] == 1]
    t2 = [d["ttft_seconds"] * 1000 for d in data if d["turn"] > 1]
    return t1, t2


b_t1, b_t2 = turn_values("baseline_multiturn.json")
l_t1, l_t2 = turn_values("llmd_multiturn.json")

fig, ax = plt.subplots(figsize=(9, 5.5))
fig.suptitle("Baseline vs. llm-d — Multi-Turn TTFT", fontsize=13, fontweight="bold")

groups = [
    ("baseline\nturn 1", b_t1, BLUE, 0.7),
    ("baseline\nturn 2+", b_t2, BLUE, 1.0),
    ("llm-d\nturn 1", l_t1, ORANGE, 0.7),
    ("llm-d\nturn 2+", l_t2, ORANGE, 1.0),
]
means = [stats.mean(v) for _, v, _, _ in groups]
medians = [stats.median(v) for _, v, _, _ in groups]
colors = [c for _, _, c, _ in groups]
alphas = [a for _, _, _, a in groups]
labels = [l for l, _, _, _ in groups]

bars = ax.bar(labels, means, color=colors)
for bar, a in zip(bars, alphas):
    bar.set_alpha(0.55 if a == 0.7 else 0.95)
ax.set_ylim(0, max(means) * 1.28)
for i, (m, med) in enumerate(zip(means, medians)):
    ax.text(i, m + max(means) * 0.04, f"mean={m:.0f}ms\nmedian={med:.0f}ms", ha="center", fontsize=9)

ax.set_ylabel("TTFT (ms)")
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

fig.text(0.5, 0.90, "Turn 1 (no cache to hit/miss) vs. turn 2+ (routing-dependent)", ha="center", fontsize=11.5)
fig.tight_layout(rect=[0, 0, 1, 0.86])
fig.savefig(os.path.join(HERE, "comparison_multiturn.png"), dpi=150)
print("Wrote comparison_multiturn.png")
