"""
Extract multi-turn conversations with LONG human turns, for testing
cache-aware routing under a longer-context regime than the original
short-prompt variant. Capped at 2 turns (not 3-4) to stay safely under
--max-model-len=8192 given much longer per-turn text: worst case
2 * (~1750 input tokens + 400 generated tokens) ~= 4300 tokens, comfortably
under the ceiling with no deployment changes needed.
"""

import json

SRC = "/private/tmp/claude-501/-Users-tanishkandivlikar-llmd-course/f9c51047-7fce-478b-b699-d6c038192d17/scratchpad/ShareGPT_V3_unfiltered_cleaned_split.json"
OUT = "/Users/tanishkandivlikar/llmd_course/benchmark/real_conversations_long.json"

HUMAN_TURNS = 2
MIN_TURN_CHARS = 1500
MAX_TURN_CHARS = 7000
NUM_TO_SELECT = 18

with open(SRC) as f:
    data = json.load(f)

candidates = []
for entry in data:
    turns = entry.get("conversations", [])
    human_turns = [t["value"] for t in turns if t.get("from") == "human"]
    if len(human_turns) < HUMAN_TURNS:
        continue
    human_turns = human_turns[:HUMAN_TURNS]
    if any(not (MIN_TURN_CHARS <= len(t) <= MAX_TURN_CHARS) for t in human_turns):
        continue
    total_chars = sum(len(t) for t in human_turns)
    candidates.append((total_chars, human_turns))

print(f"Found {len(candidates)} candidate long conversations after filtering")

candidates.sort(key=lambda x: x[0])
step = max(1, len(candidates) // NUM_TO_SELECT)
selected = [candidates[i * step][1] for i in range(min(NUM_TO_SELECT, len(candidates) // step))]

lengths = [sum(len(t) for t in turns) for turns in selected]
print(f"Selected {len(selected)} conversations, total-char-length range: {min(lengths)}-{max(lengths)} "
      f"(~{min(lengths)//4}-{max(lengths)//4} tokens for 2 human turns)")

with open(OUT, "w") as f:
    json.dump(selected, f, indent=2)

print(f"Wrote {OUT}")
