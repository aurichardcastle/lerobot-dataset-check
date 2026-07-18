# galbot-mcap2lerobot merge: silent training-data corruption at commit `904d251`

Scope of every claim below: converter repo `galbot-mcap2lerobot` at commit `904d251334fecd4b2cf8c6539cd52bf90624755d`, evaluated against `lerobot 0.3.3`. The upstream repo is currently 404 on GitHub; a local clone was the source read. Nothing here is asserted beyond what was executed or read at a named line.

---

## 1. The bug

The merge step (`merge_lerobot_v2_1.py`) turns each input MCAP-derived dataset into a one-episode sub-dataset and concatenates them. Three metadata streams are handled inconsistently: the **parquet `episode_index`** is reindexed, but **`episodes_stats`** and **`tasks`** are not. Because every sub-dataset numbers its single episode `0` and its single task `0`, the merged metadata contains N entries all still keyed at index `0`.

### Converter side — where the divergence is introduced

`src/galbot_mcap2lerobot/merge_lerobot_v2_1.py`:

- **Line 460** — `df["episode_index"] = new_index`
  Each source parquet's `episode_index` **is** rewritten to the running global index. This is the one stream that gets reindexed correctly.
- **Line 422** — `all_episode_stats.extend(ep_stats)`
  Per-episode stats are appended **verbatim**. The `episode_index` field inside each stats record is never rewritten, so every sub-dataset contributes a record still labelled `episode_index: 0`.
- **Line 425** — `if task not in all_tasks:`
  Tasks are deduplicated by whole-dict equality and appended. The `task_index` field is never remapped, so two distinct tasks each arrive carrying `task_index: 0`.

Net metadata state after merging N single-episode files: `episodes_stats.jsonl` has N rows all at `episode_index 0`; `tasks.jsonl` has up-to-N rows all at `task_index 0`; the parquet `episode_index` column, by contrast, is a clean contiguous `0..N-1`. The parquet and the sidecar metadata now disagree.

### Loader side — why LeRobot loads it clean, with no error

`lerobot 0.3.3` (confirmed against `lerobot-0.3.3.dist-info`) ingests both sidecars into **dicts keyed by the index field**, so colliding keys silently overwrite — last-wins — instead of raising:

- `datasets/utils.py:210` — `load_tasks`:
  `tasks = {item["task_index"]: item["task"] for item in sorted(tasks, key=lambda x: x["task_index"])}`
  N rows all at `task_index 0` collapse to a **single** dict entry `{0: <last task string>}`.
- `datasets/utils.py:234` — `load_episodes_stats`:
  `{item["episode_index"]: cast_stats_to_numpy(item["stats"]) for item in sorted(...)}`
  N stats records all at `episode_index 0` collapse to **one** surviving stats entry.
- `datasets/lerobot_dataset.py:113` —
  `self.stats = aggregate_stats(list(self.episodes_stats.values()))`
  Global normalization statistics are aggregated over **only the surviving values** — i.e. one episode's stats stand in for the whole merged dataset.
- `datasets/lerobot_dataset.py:730` —
  `item["task"] = self.meta.tasks[task_idx]`
  Per-frame the task string is looked up through the collapsed `tasks` dict, using the `task_index` stored in the parquet. Because `task_index` is never remapped, both episodes' frames carry `task_index 0` and resolve to the single surviving (last-wins) task string.

Because both sidecars are dict-keyed, the structural inconsistency never surfaces as a KeyError or a validation failure. The dataset loads and iterates without error. That is what makes this a silent-corruption bug rather than a crash.

### Verified consequences (observed, not inferred)

After a two-file merge:

- `episodes_stats` collapses to a single episode's stats, so the **global normalization is computed from one episode** instead of two.
- Both episodes' frames resolve to the **same task string** (`"open the drawer"`). Frames that were captured for `"pick up the red cube"` are served to the consumer under the wrong label.

What is **not** claimed: that the trained policy performs worse. That is a downstream inference and is deliberately left to you. The facts asserted stop at the data layer: wrong normalization inputs and mislabeled frames.

---

## 2. Reproduction (~30 s, zero robot data)

`upstream/repro_stats_collision.py` — zero third-party dependencies, no MCAPs, no robot data. It fabricates two one-episode LeRobot datasets (tasks `"pick up the red cube"` and `"open the drawer"`), invokes the converter's **own** merge function, then reads the merged metadata back the way LeRobot's loader would.

Run against the **pristine** converter at `904d251`:
- prints `episodes_stats indices: [0, 0]`
- the reconstructed task dict collapses to `{0: 'open the drawer'}` (the cube task is gone)
- exits non-zero (`exit 1`)

Run against the **patched** converter (patches from §3 applied):
- prints `episodes_stats indices: [0, 1]`
- task dict is `{0: 'pick up the red cube', 1: 'open the drawer'}`
- exits `0`

The script lets an engineer confirm the mechanism without touching the robot-data pipeline, and it doubles as a regression guard: it passes only when the reindexing is correct in both streams.

---

## 3. The three patches

Git-format patches in `upstream/` (`0001…`, `0002…`, `0003…`). Each is one focused change:

- **0001 — reindex `episodes_stats`.** In the same accumulation loop that already computes `new_index`, rewrite each stats record's `episode_index` to the global index before `extend`. Fixes the `line 422` divergence so stats records land at `0..N-1` and no longer collide in `load_episodes_stats`.
- **0002 — remap parquet `task_index` into the merged task table.** Build a per-sub-dataset map from local `task_index` to the deduplicated global `task_index`, and rewrite the parquet `task_index` column accordingly (alongside the existing `episode_index` rewrite at `line 460`). Fixes the `line 425` divergence so each frame resolves to the correct task string.
- **0003 — rewrite the global `index` column and reconcile `info.json` totals.** Make the global frame `index` contiguous across the merged output and recompute `info.json` `total_tasks`, `total_videos`, and `splits`.
  Note on `splits`: the value the converter emitted (`"0:{n-1}"`) is **cosmetic only** — LeRobot never reads `splits` on load (its own writer sets `"0:{total_episodes}"` at `lerobot_dataset.py:261`). Patch 0003 tidies it while it is recomputing the other totals; it is **not** a bug on its own and is not represented as one.

### Before / after — verified by re-running the actual merge

The patches were applied to a scratch copy of the converter and its **real merge** was re-run on the `run1` inputs. The merged output was then checked two independent ways: with `lerobot-dataset-check` (§4) **and** by loading it through LeRobot's own `LeRobotDataset`.

- Before: **5 FAIL**
- After: **11 PASS / 0 FAIL**

Post-fix semantic spot check on the merged output: episode `0` → `task_index 0` → `"pick up the red cube"`; episode `1` → `task_index 1` → `"open the drawer"`; global `index` contiguous `0..177`. Both the cube and drawer tasks survive, each frame carries its own label, and normalization aggregates over both episodes.

---

## 4. `lerobot-dataset-check`

A standalone read-only validator (separate repo, MIT, author Auric, https://github.com/aurichardcastle/lerobot-dataset-check), published as an upstream ecosystem contribution rather than a private artifact. Six checks:

1. `episodes_stats` ↔ episodes bijection (every episode has exactly one stats record and vice versa).
2. `task_index` uniqueness and resolvability (no colliding keys; every parquet `task_index` resolves).
3. parquet ↔ metadata layout agreement.
4. `info.json` totals consistency.
5. global `index` contiguity.
6. timestamp monotonicity/consistency.

**Why it takes no dependency on `lerobot` itself:** it reads `meta/*.jsonl` and the parquet files directly. The whole failure mode in §1 exists *because* LeRobot's loader collapses colliding keys into dicts and thereby hides the inconsistency — a checker that went through the same loader would inherit the same blind spot. Reading the raw sidecars is precisely what lets it catch what the loader swallows. 7/7 of its own unit tests pass.

**Prior art, stated plainly:** Trajlens (Apache-2.0, https://github.com/Kunal-Somani/trajlens) is a broader, pre-existing LeRobot linter that includes auto-fixers. It is linked in the README. This tool is positioned as narrow and complementary — it makes no novelty claim over Trajlens.

---

## 5. Public-dataset scan

To test for damage in the wild (not just the mechanism), 19 public Galbot-G1 LeRobot datasets were scanned for the metadata fingerprint. **Zero flagged.** Six were fully readable and all clean — but all six are single-task, so they are structurally uninformative about a multi-file/multi-task merge: they may never exercise the buggy path. The remaining 13 are access-gated (HTTP 401); access has been requested and is pending. Publishers are the vendor "RoboCOIN" and "wangtao716", not Galbot itself.

Neutral bottom line: no corrupted public dataset was found, the readable public surface is clean, and the highest-risk artifacts remain unverified. This neither confirms nor refutes corruption in published data.

---

## 6. Appendix

### Reserve findings (doc/hygiene tier, all verified)

- `example8_real_time_control_loop.py` is byte-identical to `example1` in both the g1 and s1 example sets.
- RGB/depth comments are inverted across ~9 files.
- `deploy_to_robot.sh` Step-8 verification flags are echoed but never actually tested.
- README docs URL `localhost:8000/en/` returns 404.
- `docker/compose.yaml` mounts `/etc/shadow` (`:ro`).

### Footnote — kinematics / mass (`galbot-model-check`)

The robot description files' kinematics check out exactly: left-arm chain measures 710.0 mm against a 710 mm datasheet figure (0.00%). One open question, posed as a question and not a discrepancy: the model totals ~112 kg versus the datasheet 机身重量 of 92.5 kg; model-minus-arms-minus-head ≈ 91.3 kg, so the spec figure appears to exclude arms and head — is that the intended scope of the 92.5 kg number?

---

## Verification table

| # | Claim | How it was verified |
|---|-------|---------------------|
| 1 | Repo is at commit `904d251334fecd4b2cf8c6539cd52bf90624755d` | `git log` on the local clone → `904d251 refactor joint layout metadata` |
| 2 | Converter reindexes parquet `episode_index` | Read `src/galbot_mcap2lerobot/merge_lerobot_v2_1.py:460` → `df["episode_index"] = new_index` |
| 3 | Converter appends `episodes_stats` verbatim (no reindex) | Read `merge_lerobot_v2_1.py:422` → `all_episode_stats.extend(ep_stats)` |
| 4 | Converter dedupes tasks without remapping `task_index` | Read `merge_lerobot_v2_1.py:425` → `if task not in all_tasks:` |
| 5 | LeRobot keys tasks by `task_index` (collision → last-wins) | Read `lerobot/datasets/utils.py:210` (lerobot 0.3.3) |
| 6 | LeRobot keys stats by `episode_index` (collision → last-wins) | Read `lerobot/datasets/utils.py:234` |
| 7 | Global normalization aggregates surviving stats values only | Read `lerobot/datasets/lerobot_dataset.py:113` |
| 8 | Per-frame task label read through collapsed dict | Read `lerobot/datasets/lerobot_dataset.py:730` |
| 9 | `splits` is never read on load (cosmetic) | Read `lerobot/datasets/lerobot_dataset.py:261` — LeRobot's own writer sets `"0:{total_episodes}"` |
| 10 | lerobot version under test is 0.3.3 | Present as `lerobot-0.3.3.dist-info` in the venv |
| 11 | Repro prints `[0, 0]` / task dict collapses / exit 1 against pristine | Executed `upstream/repro_stats_collision.py` this session |
| 12 | Repro prints `[0, 1]` / dict `{0:cube,1:drawer}` / exit 0 against patched | Executed the same script against the patched converter this session |
| 13 | Two-episode merge collapses stats to one episode + mislabels frames | Observed by running the converter's own merge and reading back merged metadata |
| 14 | Patches move output from 5 FAIL → 11 PASS / 0 FAIL | Re-ran the actual merge on `run1` inputs, checked with both `lerobot-dataset-check` and LeRobot's own loader |
| 15 | Post-fix: ep0→cube, ep1→drawer, global index 0..177 contiguous | Semantic inspection of the patched merge output |
| 16 | Three patches exist in `upstream/` | Directory listing: `0001-…`, `0002-…`, `0003-….patch` |
| 17 | `lerobot-dataset-check` 7/7 unit tests pass | Ran the tool's unit suite this session |
| 18 | Public scan: 19 datasets, 0 flagged, 6 readable+clean+single-task, 13 gated (401) | Scan executed this session; results recorded |
| 19 | Left-arm chain 710.0 mm vs 710 mm datasheet (0.00%) | `galbot-model-check` run against the description files |
| 20 | Reserve findings (example8 dupe, inverted comments, deploy Step-8, 404 URL, `/etc/shadow` mount) | Each read/executed against the repo this session |

Any claim not represented above is either omitted or explicitly marked as inference (notably: no assertion that the trained policy performs worse — that is left to the reader).

**Authorship:** built with heavy AI assistance; every file:line reference and every number above was verified by hand against the real repo at commit `904d251` and against `lerobot 0.3.3` source.
