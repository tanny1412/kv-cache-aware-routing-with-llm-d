"""
Extract a diverse, curated set of real multi-turn conversations from the
ShareGPT dataset for use in multiturn_bench.py.

We only keep the human turns (our own live server generates its own replies
when we replay these — we don't use ShareGPT's original GPT responses at
all). We deliberately select a *spread* of short, medium, and long
conversations by total human-turn character count, rather than just taking
the first N, so the benchmark actually exercises varied context sizes.
"""

import json
import random

SRC = "/private/tmp/claude-501/-Users-tanishkandivlikar-llmd-course/f9c51047-7fce-478b-b699-d6c038192d17/scratchpad/ShareGPT_V3_unfiltered_cleaned_split.json"
OUT = "/Users/tanishkandivlikar/llmd_course/benchmark/real_conversations.json"

MIN_HUMAN_TURNS = 3
MAX_HUMAN_TURNS = 4
MAX_SINGLE_TURN_CHARS = 1500  # skip conversations with a single extreme-length turn (e.g. code dumps)
NUM_TO_SELECT = 18

random.seed(42)

with open(SRC) as f:
    data = json.load(f)

candidates = []
for entry in data:
    turns = entry.get("conversations", [])
    human_turns = [t["value"] for t in turns if t.get("from") == "human"]
    if not (MIN_HUMAN_TURNS <= len(human_turns) <= MAX_HUMAN_TURNS):
        continue
    if any(len(t) > MAX_SINGLE_TURN_CHARS for t in human_turns):
        continue
    total_chars = sum(len(t) for t in human_turns)
    if total_chars < 50:
        continue
    candidates.append((total_chars, human_turns))

print(f"Found {len(candidates)} candidate conversations after filtering")

# Sort by total length, then pick evenly spaced samples across the whole
# range (short -> long) so we get real variety, not a random cluster around
# the median.
candidates.sort(key=lambda x: x[0])
step = len(candidates) // NUM_TO_SELECT
selected = [candidates[i * step][1] for i in range(NUM_TO_SELECT)]

lengths = [sum(len(t) for t in turns) for turns in selected]
print(f"Selected {len(selected)} conversations, total-char-length range: {min(lengths)}-{max(lengths)}")

with open(OUT, "w") as f:
    json.dump(selected, f, indent=2)

print(f"Wrote {OUT}")
