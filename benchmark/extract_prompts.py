"""
Extract a pool of single-turn prompts of varied length from ShareGPT, for the
load-curve benchmark (concurrency sweep). Unlike extract_conversations.py,
we only need the *first* human turn of each conversation here -- this
benchmark stresses prefill/decode contention via a realistic mix of short and
long prompts under concurrent load, not multi-turn cache locality.
"""

import json

SRC = "/private/tmp/claude-501/-Users-tanishkandivlikar-llmd-course/f9c51047-7fce-478b-b699-d6c038192d17/scratchpad/ShareGPT_V3_unfiltered_cleaned_split.json"
OUT = "/Users/tanishkandivlikar/llmd_course/benchmark/load_curve_prompts.json"

MIN_CHARS = 20
MAX_CHARS = 2000
NUM_TO_SELECT = 100

with open(SRC) as f:
    data = json.load(f)

candidates = []
for entry in data:
    turns = entry.get("conversations", [])
    if not turns or turns[0].get("from") != "human":
        continue
    text = turns[0]["value"]
    if MIN_CHARS <= len(text) <= MAX_CHARS:
        candidates.append(text)

print(f"Found {len(candidates)} candidate prompts after filtering")

candidates.sort(key=len)
step = len(candidates) // NUM_TO_SELECT
selected = [candidates[i * step] for i in range(NUM_TO_SELECT)]

lengths = [len(p) for p in selected]
print(f"Selected {len(selected)} prompts, char-length range: {min(lengths)}-{max(lengths)}")

with open(OUT, "w") as f:
    json.dump(selected, f, indent=2)

print(f"Wrote {OUT}")
