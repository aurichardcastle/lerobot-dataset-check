# lerobot-dataset-check

Read-only integrity checks for [LeRobot](https://github.com/huggingface/lerobot)
v2.1 datasets. Point it at a dataset directory, get a PASS/WARN/FAIL report and
a CI-friendly exit code.

Built by Auric. MIT licensed.

```bash
pip install -r requirements.txt        # pandas + pyarrow only
python -m lerobot_dataset_check /path/to/dataset
```

Exit codes: `0` no failures, `1` at least one FAIL, `2` usage error.
WARN never fails the build.

## Why this exists

Converters and merges are where silent corruption creeps into robot-learning
datasets — and most of that damage **loads without any error**, because the
LeRobot loader keys metadata into dicts and trusts the result:

- `load_episodes_stats` builds `{episode_index: stats}` — if two entries share
  an index (the classic multi-file merge bug), they silently overwrite
  last-wins, and the global normalization stats are then aggregated from a
  **subset** of episodes.
- `load_tasks` builds `{task_index: task}` the same way — colliding task rows
  collapse to one string, and every frame pointing at that index is silently
  relabeled at training time.
- `info.json` totals are read and trusted, never reconciled against the actual
  files.

None of that crashes. The policy just trains on mis-normalized, mislabeled
data, and you find out weeks later when it underperforms for no visible
reason. Reading the raw files directly (no lerobot dependency) is what makes
these problems visible — which is the whole design of this tool.

## The checks

| # | check | catches | severity |
|---|---|---|---|
| 1 | stats ↔ episodes bijection | colliding / missing `episodes_stats` entries (silent mis-normalization) | FAIL |
| 2 | task label integrity | duplicate `task_index` rows (silent frame relabeling); unresolvable indices | FAIL |
| 3 | parquet ↔ metadata layout | `episode_index` column vs filename; row counts vs declared lengths | FAIL |
| 4 | info.json totals | `total_episodes` / `total_frames` / `total_tasks` vs reality; stale splits & video counts | FAIL / WARN |
| 5 | global `index` contiguity | merges that copy parquet without rewriting the global frame index | FAIL |
| 6 | timestamps | non-monotonic time (FAIL); frame-gap drift vs `1/fps` (WARN) | FAIL / WARN |

## Sample report (a real corrupted merge)

This is the output on a dataset produced by merging two single-episode
conversions with a merge step that reindexed episodes but not their stats or
task indices:

```
[ Episode stats <-> episodes ]
  [FAIL] episodes_stats.jsonl has colliding episode_index [0] (indices found:
         [0, 0], episodes are: [0, 1]). The loader keys stats by this index, so
         colliding entries silently overwrite and normalization stats come from
         a subset of episodes.
  [FAIL] episodes with no stats entry: [1]

[ Task labels ]
  [FAIL] tasks.jsonl has colliding task_index [0] across tasks ['pick up the
         red cube', 'open the drawer']. The loader keeps only the last one, so
         frames of the earlier task(s) get silently relabeled at training time.

[ Global frame index ]
  [FAIL] 'index' is not contiguous: at global position 88 found 0, expected 88

 SUMMARY: 5 PASS, 2 WARN, 5 FAIL, 0 INFO
 RESULT: FAIL   exit code 1
```

The same tool on each pre-merge dataset: `11 PASS, 0 WARN, 0 FAIL`, exit 0.

## Related work (read this before assuming novelty)

- [Trajlens](https://github.com/Kunal-Somani/trajlens) is a broader
  LeRobot-dataset linter with more checks, auto-fixers, and Hub auditing. If
  you want a full quality suite, start there. This tool is deliberately
  narrower: six read-only checks, no fixers, no lerobot dependency, small
  enough to read in one sitting — built around the merge-collision failure
  modes (checks 1 and 2) that load silently.
- LeRobot itself hard-enforces timestamp spacing at load
  (`check_timestamps_sync`), so check 6 partially overlaps it; the
  metadata-bijection and totals-reconciliation checks (1–4) are the ones the
  loader does not cover.

## Limitations

- Written against the v2.1 layout (`meta/*.jsonl` + chunked parquet); other
  versions get a WARN and best-effort checks.
- Video checks are file-existence/counting only — no decoding.
- Stats *values* are not recomputed (that's expensive and Trajlens covers it);
  this tool checks the indexing that decides whether stats are *used* correctly.

## CI

```yaml
- run: pip install -r requirements.txt
- run: python -m lerobot_dataset_check datasets/my_dataset
```
