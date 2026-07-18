# galbot-mcap2lerobot — silent data corruption in the multi-file merge

**This matters only if your internal training pipeline runs through the released multi-file merge path in `galbot-mcap2lerobot` (commit `904d251`).** If your pipeline diverged from that code, skip to the checker at the bottom — it closes the gap either way. What the merge does: when it combines N MCAP files it reindexes each episode's *frames* correctly (`merge_lerobot_v2_1.py:460`), but appends each file's per-episode **stats** verbatim (`:422`) and dedupes **tasks** by dict-equality without remapping `task_index` (`:425`) — so every merged episode's stats and task entry keep index 0. LeRobot 0.3.3 loads both as index-keyed dicts, last-wins, no error (`utils.py:210`, `:234`). Observed after a 2-file merge: `episodes_stats` indices `[0, 0]` collapse to one entry, so global normalization is computed from a single episode's stats; and both episodes' frames resolve through the collapsed task dict to the **same** label — "pick up the red cube" frames are served as "open the drawer". These are data-level facts at commit `904d251` / lerobot 0.3.3; I'm not claiming a training-quality delta — that inference is yours.

*The repo went 404 on GitHub before I could file this publicly, so I'm sending it directly.*

## Run it yourself (~30s, no MCAPs, no robot data)

```
python upstream/repro_stats_collision.py
```

Fabricates two 1-episode datasets, runs **their** merge, prints the collision. Against the pristine converter: `episodes_stats indices: [0, 0]`, task dict collapses to `{0: 'open the drawer'}`, exit 1. Against the patched converter: `[0, 1]`, `{0: 'pick up the red cube', 1: 'open the drawer'}`, exit 0. Captured output of both runs: `upstream/repro_output.txt` (in case you'd rather read than run).

## Patches (`upstream/`, git-format)

- **0001** — reindex `episodes_stats` to the new episode index.
- **0002** — remap `task_index` on merge instead of deduping by dict equality.
- **0003** — assign a contiguous global `index`; recompute `info.json` totals. *(Also rewrites the cosmetic `splits` field — LeRobot never reads it on load; noted so you know it changed, not flagged as a bug.)*

Verified by applying all three to a scratch copy and re-running their actual merge on the run1 inputs: 5 FAIL → 11 PASS / 0 FAIL, confirmed by both `lerobot-dataset-check` and LeRobot's own loader. Post-fix: episode 0 → task 0 "pick up the red cube", episode 1 → task 1 "open the drawer", global `index` 0..177 contiguous.

## `lerobot-dataset-check` — upstream ecosystem contribution

Standalone tool (MIT, https://github.com/aurichardcastle/lerobot-dataset-check), 6 read-only checks: stats↔episodes bijection, task_index uniqueness/resolution, parquet↔metadata layout, info.json totals, global-index contiguity, timestamps. Reads `meta/*.jsonl` + parquet directly with no dependency on lerobot — which is *why* it catches what the loader silently swallows. 7/7 unit tests pass. Prior art acknowledged in the README: Trajlens (Apache-2.0, https://github.com/Kunal-Somani/trajlens) is a broader existing linter with auto-fixers; this is positioned as narrow and complementary, no novelty claim.

*Public-dataset scan, for completeness:* 19 public Galbot-G1 LeRobot datasets scanned for the fingerprint — 0 flagged; the 6 fully-readable ones are clean but all single-task, so structurally uninformative about a multi-file merge; 13 are access-gated (HTTP 401), access requested and pending. No corrupted public dataset found; the highest-risk artifacts remain unverified.

---

*Footnote — `galbot-model-check`:* robot-description kinematics match the datasheet exactly (left-arm chain 710.0 mm vs 710 mm, 0.00%). One question, not a discrepancy: model total ~112 kg vs datasheet 机身重量 92.5 kg; model-minus-arms-minus-head ≈ 91.3 kg, so the spec figure likely excludes arms+head — is that the intended scope?

*Built with heavy AI assistance; every line number, index, and pass/fail count above was verified by hand against your actual repo at commit `904d251`.*
