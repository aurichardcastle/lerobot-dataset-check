"""Load the on-disk pieces of a LeRobot v2.1 dataset directly.

Deliberately does NOT import lerobot. The whole point of this checker is
to catch problems the lerobot loader silently swallows (it keys metadata
into dicts, so duplicate indices overwrite last-wins and load "cleanly").
Reading the raw files with pandas/pyarrow is what makes those visible.
"""
from __future__ import annotations

import json
import pathlib
import re

import pandas as pd

EPISODE_PARQUET_RE = re.compile(r"episode_(\d{6})\.parquet$")


class Dataset:
    """Raw file contents of one dataset directory."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        meta = root / "meta"
        self.info = _load_json(meta / "info.json")
        self.episodes = _load_jsonl(meta / "episodes.jsonl")
        self.episodes_stats = _load_jsonl(meta / "episodes_stats.jsonl")
        self.tasks = _load_jsonl(meta / "tasks.jsonl")

        # parquet files: {episode_index_from_filename: path}
        self.parquets = {}
        for p in sorted(root.glob("data/chunk-*/episode_*.parquet")):
            m = EPISODE_PARQUET_RE.search(p.name)
            if m:
                self.parquets[int(m.group(1))] = p

    def read_parquet(self, episode_index: int) -> pd.DataFrame:
        return pd.read_parquet(self.parquets[episode_index])


def _load_json(path: pathlib.Path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _load_jsonl(path: pathlib.Path):
    if not path.exists():
        return None
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def open_dataset(root_str: str) -> Dataset:
    root = pathlib.Path(root_str)
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a directory")
    if not (root / "meta").is_dir():
        raise FileNotFoundError(f"{root} has no meta/ directory (not a LeRobot dataset?)")
    return Dataset(root)
