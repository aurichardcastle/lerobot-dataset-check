"""Tests build tiny synthetic datasets on disk and run the real checks."""
import json
import pathlib
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lerobot_dataset_check import checks, loaders, report


def make_dataset(root, stats_indices, task_rows, global_index_restarts=False):
    """Write a minimal 2-episode v2.1 dataset; knobs inject the two bugs."""
    root = pathlib.Path(root)
    (root / "meta").mkdir(parents=True)
    (root / "data/chunk-000").mkdir(parents=True)
    lengths = [3, 2]
    with open(root / "meta/info.json", "w") as f:
        json.dump(
            {
                "codebase_version": "v2.1",
                "total_episodes": 2,
                "total_frames": sum(lengths),
                "total_tasks": len({r["task"] for r in task_rows}),
                "fps": 30,
                "splits": {"train": "0:2"},
                "features": {},
            },
            f,
        )
    with open(root / "meta/episodes.jsonl", "w") as f:
        for i, n in enumerate(lengths):
            f.write(json.dumps({"episode_index": i, "tasks": ["t"], "length": n}) + "\n")
    with open(root / "meta/episodes_stats.jsonl", "w") as f:
        for i in stats_indices:
            f.write(json.dumps({"episode_index": i, "stats": {}}) + "\n")
    with open(root / "meta/tasks.jsonl", "w") as f:
        for row in task_rows:
            f.write(json.dumps(row) + "\n")

    start = 0
    for i, n in enumerate(lengths):
        idx = list(range(0, n)) if global_index_restarts else list(range(start, start + n))
        df = pd.DataFrame(
            {
                "timestamp": [k / 30 for k in range(n)],
                "frame_index": list(range(n)),
                "episode_index": [i] * n,
                "index": idx,
                "task_index": [0] * n,
            }
        )
        df.to_parquet(root / f"data/chunk-000/episode_{i:06d}.parquet", index=False)
        start += n


def statuses(section):
    return [s for s, _ in section.findings]


class TestStatsBijection(unittest.TestCase):
    def test_collision_fails(self):
        with tempfile.TemporaryDirectory() as d:
            make_dataset(d, stats_indices=[0, 0], task_rows=[{"task_index": 0, "task": "t"}])
            sec = checks.check_stats_bijection(loaders.open_dataset(d))
            self.assertIn(report.FAIL, statuses(sec))

    def test_clean_passes(self):
        with tempfile.TemporaryDirectory() as d:
            make_dataset(d, stats_indices=[0, 1], task_rows=[{"task_index": 0, "task": "t"}])
            sec = checks.check_stats_bijection(loaders.open_dataset(d))
            self.assertEqual(statuses(sec), [report.PASS])


class TestTaskIntegrity(unittest.TestCase):
    def test_duplicate_task_index_fails(self):
        with tempfile.TemporaryDirectory() as d:
            make_dataset(
                d,
                stats_indices=[0, 1],
                task_rows=[
                    {"task_index": 0, "task": "pick"},
                    {"task_index": 0, "task": "open"},
                ],
            )
            sec = checks.check_task_integrity(loaders.open_dataset(d))
            self.assertIn(report.FAIL, statuses(sec))

    def test_unique_passes(self):
        with tempfile.TemporaryDirectory() as d:
            make_dataset(d, stats_indices=[0, 1], task_rows=[{"task_index": 0, "task": "t"}])
            sec = checks.check_task_integrity(loaders.open_dataset(d))
            self.assertNotIn(report.FAIL, statuses(sec))


class TestGlobalIndex(unittest.TestCase):
    def test_restart_fails(self):
        with tempfile.TemporaryDirectory() as d:
            make_dataset(
                d,
                stats_indices=[0, 1],
                task_rows=[{"task_index": 0, "task": "t"}],
                global_index_restarts=True,
            )
            sec = checks.check_global_index(loaders.open_dataset(d))
            self.assertIn(report.FAIL, statuses(sec))

    def test_contiguous_passes(self):
        with tempfile.TemporaryDirectory() as d:
            make_dataset(d, stats_indices=[0, 1], task_rows=[{"task_index": 0, "task": "t"}])
            sec = checks.check_global_index(loaders.open_dataset(d))
            self.assertEqual(statuses(sec), [report.PASS])


class TestExitPath(unittest.TestCase):
    def test_has_failure_gates(self):
        good, bad = report.Section("a"), report.Section("b")
        good.add(report.WARN, "w")
        bad.add(report.FAIL, "f")
        self.assertFalse(report.has_failure([good]))
        self.assertTrue(report.has_failure([good, bad]))


if __name__ == "__main__":
    unittest.main()
