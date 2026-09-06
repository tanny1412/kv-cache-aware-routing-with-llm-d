"""
Extract a pool of LONG single-turn prompts from ShareGPT, for testing
disaggregation under the input-sequence-length regime llm-d's own docs say
it targets ("10k ISL, not 200 ISL"). Real p99+ tail of the dataset's length
distribution (checked separately: p99 ~5400 chars, p99.9 ~13700 chars).

Kept safely under --max-model-len=8192 (~32k chars) with room for
generation (max_tokens=200), so no deployment config changes needed.
"""

import json

SRC = "/private/tmp/claude-501/-Users-tanishkandivlikar-llmd-course/f9c51047-7fce-478b-b699-d6c038192d17/scratchpad/ShareGPT_V3_unfiltered_cleaned_split.json"
OUT = "/Users/tanishkandivlikar/llmd_course/benchmark/load_curve_prompts_long.json"

MIN_CHARS = 3000
MAX_CHARS = 14000
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

print(f"Found {len(candidates)} candidate long prompts after filtering")

candidates.sort(key=len)
step = max(1, len(candidates) // NUM_TO_SELECT)
selected = [candidates[i * step] for i in range(min(NUM_TO_SELECT, len(candidates) // step))]

lengths = [len(p) for p in selected]
print(f"Selected {len(selected)} prompts, char-length range: {min(lengths)}-{max(lengths)} "
      f"(~{min(lengths)//4}-{max(lengths)//4} tokens)")

with open(OUT, "w") as f:
    json.dump(selected, f, indent=2)

print(f"Wrote {OUT}")
