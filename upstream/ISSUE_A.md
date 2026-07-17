# Issue draft A — for GalaxyGeneralRobotics/galbot-mcap2lerobot

**Title:** merge: episodes_stats episode_index not reindexed → colliding stats after multi-file conversion

**Body:**

Really useful converter — I've been using it to get Galbot-style recordings into
LeRobot format. I hit one sharp edge on the multi-file path and wanted to report
it properly.

**What happens:** `merge_lerobot_v2_1.py` reindexes `episodes.jsonl` (line 415)
and the parquet `episode_index` (line 460), but appends `episodes_stats.jsonl`
entries verbatim (line 422, `all_episode_stats.extend(ep_stats)`). Since each
worker converts one MCAP into a sub-dataset whose episode is index 0, merging N
files produces N stats entries that all say `episode_index: 0`.

**Why it matters:** lerobot 0.3.3 keys stats by `episode_index`
(`lerobot/datasets/utils.py:231-236` builds a dict, so colliding entries
overwrite last-wins), then aggregates the surviving values into the global
normalization stats (`lerobot_dataset.py:112-113`). So after a 2-file merge,
normalization is silently computed from a single episode — no error, no
warning, the dataset loads fine.

**Repro:**
```bash
# convert two MCAPs separately, then merge
python -m galbot_mcap2lerobot.merge_lerobot_v2_1 \
    --source_folders out_A out_B --output_folder merged
python - <<'EOF'
import json
idx = [json.loads(l)["episode_index"] for l in open("merged/meta/episodes_stats.jsonl")]
print("stats indices:", idx)          # -> [0, 0]
assert idx == [0, 1], "stats collide!"
EOF
```

**Fix:** attached patch (`0001-...patch`) reindexes stats with the same
old→new mapping the episodes get. Happy to open it as a PR if that's easier.
