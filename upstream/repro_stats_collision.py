"""30-second repro for the merge stats/task collision.

Fabricates two tiny single-episode datasets (no MCAPs, no robot data),
runs the converter's own merge_datasets() on them, and prints what came out.

Usage:
    PYTHONPATH=/path/to/galbot-mcap2lerobot/src python repro_stats_collision.py

Expected (correct) output: stats indices [0, 1], two distinct task_index values.
Observed on current HEAD: stats indices [0, 0] and both tasks at task_index 0 —
the loader keys both by index, so one silently overwrites the other.
"""
import json
import os
import sys
import tempfile

import pandas as pd

from galbot_mcap2lerobot.merge_lerobot_v2_1 import merge_datasets


def make_source(root, task):
    os.makedirs(os.path.join(root, "meta"))
    os.makedirs(os.path.join(root, "data", "chunk-000"))
    with open(os.path.join(root, "meta", "info.json"), "w") as f:
        json.dump(
            {
                "codebase_version": "v2.1",
                "total_episodes": 1,
                "total_frames": 3,
                "total_tasks": 1,
                "chunks_size": 1000,
                "fps": 30,
                "splits": {"train": "0:1"},
                "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
                "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
                "features": {},
            },
            f,
        )
    with open(os.path.join(root, "meta", "episodes.jsonl"), "w") as f:
        f.write(json.dumps({"episode_index": 0, "tasks": [task], "length": 3}) + "\n")
    with open(os.path.join(root, "meta", "episodes_stats.jsonl"), "w") as f:
        f.write(json.dumps({"episode_index": 0, "stats": {}}) + "\n")
    with open(os.path.join(root, "meta", "tasks.jsonl"), "w") as f:
        f.write(json.dumps({"task_index": 0, "task": task}) + "\n")
    pd.DataFrame(
        {
            "timestamp": [0.0, 1 / 30, 2 / 30],
            "frame_index": [0, 1, 2],
            "episode_index": [0, 0, 0],
            "index": [0, 1, 2],
            "task_index": [0, 0, 0],
        }
    ).to_parquet(os.path.join(root, "data", "chunk-000", "episode_000000.parquet"))


def main():
    tmp = tempfile.mkdtemp(prefix="merge_repro_")
    src_a = os.path.join(tmp, "pick")
    src_b = os.path.join(tmp, "open")
    out = os.path.join(tmp, "merged")
    make_source(src_a, "pick up the red cube")
    make_source(src_b, "open the drawer")

    merge_datasets([src_a, src_b], out)

    stats_idx = [
        json.loads(l)["episode_index"]
        for l in open(os.path.join(out, "meta", "episodes_stats.jsonl"))
    ]
    tasks = [json.loads(l) for l in open(os.path.join(out, "meta", "tasks.jsonl"))]
    loader_view = {t["task_index"]: t["task"] for t in tasks}  # what load_tasks does

    print()
    print(f"episodes_stats indices: {stats_idx}    expected: [0, 1]")
    print(f"tasks.jsonl rows:       {tasks}")
    print(f"loader's task dict:     {loader_view}    (dict keyed by task_index -> last wins)")
    print()

    ok = stats_idx == [0, 1] and len({t["task_index"] for t in tasks}) == len(tasks)
    if ok:
        print("OK: no collision — merge output is consistent.")
        return 0
    print("COLLISION: stats and/or task indices collide; the loader will silently")
    print("keep one entry per index. Normalization stats come from a subset of")
    print("episodes, and frames of the earlier task get the later task's label.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
