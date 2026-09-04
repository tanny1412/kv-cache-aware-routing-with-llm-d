"""
Render benchmark/baseline_multiturn.json as a two-panel PNG chart showing the
TTFT distribution split by turn 1 (no cache to hit or miss) vs. turn 2+
(routing-dependent): a histogram overlay, and a jittered strip plot of
individual points with mean/median markers.
"""

import json
import os
import random
import statistics as stats

import matplotlib.pyplot as plt

random.seed(0)

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "baseline_multiturn.json")) as f:
    data = json.load(f)

turn1 = [d["ttft_seconds"] * 1000 for d in data if d["turn"] == 1]
turn2plus = [d["ttft_seconds"] * 1000 for d in data if d["turn"] > 1]

BLUE, ORANGE = "#2a78d6", "#eb6834"

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
fig.suptitle("Baseline Multi-Turn TTFT — round-robin, no cache-aware routing", fontsize=13, fontweight="bold")

bins = [i * 20 for i in range(0, 24)]  # 0-460ms in 20ms bins
ax1.hist(turn1, bins=bins, color=BLUE, alpha=0.6, label=f"turn 1 (n={len(turn1)})")
ax1.hist(turn2plus, bins=bins, color=ORANGE, alpha=0.6, label=f"turn 2+ (n={len(turn2plus)})")
ax1.set_xlabel("TTFT (ms)")
ax1.set_ylabel("count")
ax1.set_title("Distribution: turn 1 vs. turn 2+")
ax1.legend(frameon=False)
ax1.spines["top"].set_visible(False)
ax1.spines["right"].set_visible(False)

groups = [("turn 1", turn1, BLUE), ("turn 2+", turn2plus, ORANGE)]
for i, (label, values, color) in enumerate(groups):
    jitter = [i + random.uniform(-0.15, 0.15) for _ in values]
    ax2.scatter(jitter, values, color=color, alpha=0.5, s=22, edgecolors="none")
    mean_v, median_v = stats.mean(values), stats.median(values)
    ax2.hlines(mean_v, i - 0.25, i + 0.25, color=color, linewidth=2.5)
    ax2.hlines(median_v, i - 0.25, i + 0.25, color=color, linewidth=2.5, linestyles="dotted")

ax2.set_xticks([0, 1])
ax2.set_xticklabels(["turn 1", "turn 2+"])
ax2.set_ylabel("TTFT (ms)")
ax2.set_title("Individual requests (solid = mean, dotted = median)")
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_visible(False)
ax2.set_xlim(-0.5, 1.5)

fig.tight_layout(rect=[0, 0, 1, 0.94])
out_path = os.path.join(HERE, "baseline_multiturn.png")
fig.savefig(out_path, dpi=150)
print(f"Wrote {out_path}")
