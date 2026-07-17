# Issue draft B — for GalaxyGeneralRobotics/galbot-mcap2lerobot

**Title:** merge: task_index not remapped → frames silently relabeled when merging datasets with different tasks

**Body:**

Follow-up to the stats-reindex issue — same merge path, different field.

**What happens:** the parquet copy rewrites only `episode_index` (line 460);
`task_index` is copied unchanged. `tasks.jsonl` rows are deduped by whole-dict
equality (lines 424-426), so two source datasets that each used
`task_index: 0` for *different* tasks produce two colliding rows:

```
{"task_index": 0, "task": "pick up the red cube"}
{"task_index": 0, "task": "open the drawer"}
```

**Why it matters:** lerobot's `load_tasks` (`utils.py:208-212`) builds
`{task_index: task}` — last wins — and `__getitem__`
(`lerobot_dataset.py:729-730`) labels frames from the parquet `task_index`
through that dict. In my repro, every frame of both episodes comes back as
"open the drawer"; the "pick up the red cube" label is unreachable at training
time (episodes.jsonl still has it, but the frame path never reads it).

**Repro:**
```bash
python -m galbot_mcap2lerobot.merge_lerobot_v2_1 \
    --source_folders out_pick out_open --output_folder merged
python - <<'EOF'
import json
rows = [json.loads(l) for l in open("merged/meta/tasks.jsonl")]
idx = [r["task_index"] for r in rows]
assert len(set(idx)) == len(idx), f"colliding task_index: {rows}"
EOF
```

**Fix:** attached patch (`0002-...patch`) merges tasks by task *string* with
fresh unique indices and remaps each parquet's `task_index` through the
per-source mapping. A third small patch (`0003-...patch`) also rewrites the
global `index` column (currently restarts at 0 per merged episode) and
recomputes `total_tasks` / `splits` / `total_videos` in `info.json`, which are
otherwise carried over stale from the first source. Happy to open any of these
as PRs.
