"""The six checks.

Each takes the Dataset and returns a report.Section. FAIL is reserved for
provable internal inconsistency; WARN for things that might be intentional;
INFO for context. The first two checks target the failure modes that the
lerobot loader cannot see (it keys stats and tasks by index into dicts,
so colliding indices silently overwrite last-wins).
"""
from __future__ import annotations

from .report import FAIL, INFO, PASS, WARN, Section


def check_stats_bijection(ds) -> Section:
    """episodes_stats.jsonl must carry exactly one entry per episode.

    If two entries share an episode_index, lerobot's load keeps only the
    last one, and global normalization stats get computed from a subset
    of episodes -- silently. This is the classic multi-file merge bug.
    """
    sec = Section("Episode stats <-> episodes")
    if ds.episodes is None or ds.episodes_stats is None:
        sec.add(WARN, "episodes.jsonl or episodes_stats.jsonl missing; skipping")
        return sec
    ep_idx = [e.get("episode_index") for e in ds.episodes]
    st_idx = [s.get("episode_index") for s in ds.episodes_stats]

    dup_st = sorted({i for i in st_idx if st_idx.count(i) > 1})
    if dup_st:
        sec.add(
            FAIL,
            f"episodes_stats.jsonl has colliding episode_index {dup_st} "
            f"(indices found: {st_idx}, episodes are: {sorted(ep_idx)}). "
            "The loader keys stats by this index, so colliding entries "
            "silently overwrite and normalization stats come from a subset "
            "of episodes.",
        )
    missing = sorted(set(ep_idx) - set(st_idx))
    extra = sorted(set(st_idx) - set(ep_idx))
    if missing:
        sec.add(FAIL, f"episodes with no stats entry: {missing}")
    if extra:
        sec.add(FAIL, f"stats entries for nonexistent episodes: {extra}")
    if not dup_st and not missing and not extra:
        sec.add(PASS, f"stats entries match episodes exactly ({len(ep_idx)} episodes)")
    return sec


def check_task_integrity(ds) -> Section:
    """task_index must be unique in tasks.jsonl and resolvable from parquet.

    Duplicate task_index rows collapse last-wins in the loader, so every
    frame pointing at that index gets the surviving task string -- frames
    from other tasks are silently relabeled.
    """
    sec = Section("Task labels")
    if ds.tasks is None:
        sec.add(WARN, "tasks.jsonl missing; skipping")
        return sec
    idx = [t.get("task_index") for t in ds.tasks]
    dup = sorted({i for i in idx if idx.count(i) > 1})
    if dup:
        collided = [t.get("task") for t in ds.tasks if t.get("task_index") in dup]
        sec.add(
            FAIL,
            f"tasks.jsonl has colliding task_index {dup} across tasks {collided}. "
            "The loader keeps only the last one, so frames of the earlier "
            "task(s) get silently relabeled at training time.",
        )
    else:
        sec.add(PASS, f"task_index unique across {len(idx)} task(s)")

    # every task_index used in the data must resolve
    used = set()
    for e_idx in ds.parquets:
        df = ds.read_parquet(e_idx)
        if "task_index" in df.columns:
            used.update(int(v) for v in df["task_index"].unique())
    unresolvable = sorted(used - set(idx))
    if unresolvable:
        sec.add(FAIL, f"parquet task_index values with no tasks.jsonl entry: {unresolvable}")
    elif used:
        sec.add(PASS, f"all parquet task_index values resolve ({sorted(used)})")
    return sec


def check_parquet_layout(ds) -> Section:
    """Each parquet's episode_index column must match its filename, and its
    row count must match the episode's declared length."""
    sec = Section("Parquet <-> metadata layout")
    if ds.episodes is None:
        sec.add(WARN, "episodes.jsonl missing; skipping")
        return sec
    lengths = {e["episode_index"]: e.get("length") for e in ds.episodes}
    declared = set(lengths)
    on_disk = set(ds.parquets)
    for missing in sorted(declared - on_disk):
        sec.add(FAIL, f"episode {missing} declared in episodes.jsonl but no parquet file found")
    for extra in sorted(on_disk - declared):
        sec.add(FAIL, f"parquet file for episode {extra} not declared in episodes.jsonl")
    ok = 0
    for e_idx in sorted(declared & on_disk):
        df = ds.read_parquet(e_idx)
        col = sorted(df["episode_index"].unique()) if "episode_index" in df.columns else ["<no column>"]
        if col != [e_idx]:
            sec.add(FAIL, f"episode_{e_idx:06d}.parquet has episode_index column {col}, expected [{e_idx}]")
        elif lengths[e_idx] is not None and len(df) != lengths[e_idx]:
            sec.add(FAIL, f"episode {e_idx}: parquet has {len(df)} rows, episodes.jsonl says length {lengths[e_idx]}")
        else:
            ok += 1
    if ok:
        sec.add(PASS, f"{ok} episode parquet(s) match filename + declared length")
    return sec


def check_info_totals(ds) -> Section:
    """info.json totals must agree with what is actually on disk."""
    sec = Section("info.json totals")
    if ds.info is None:
        sec.add(FAIL, "meta/info.json missing")
        return sec
    n_ep = len(ds.episodes or [])
    n_frames = sum(e.get("length", 0) for e in (ds.episodes or []))
    n_tasks_lines = len(ds.tasks or [])
    n_tasks_unique = len({t.get("task") for t in (ds.tasks or [])})

    for key, actual, label in [
        ("total_episodes", n_ep, "episodes.jsonl entries"),
        ("total_frames", n_frames, "sum of episode lengths"),
    ]:
        declared = ds.info.get(key)
        if declared != actual:
            sec.add(FAIL, f"{key} = {declared} but {label} = {actual}")
        else:
            sec.add(PASS, f"{key} = {declared} matches {label}")

    declared_tasks = ds.info.get("total_tasks")
    if declared_tasks not in (n_tasks_lines, n_tasks_unique):
        sec.add(
            FAIL,
            f"total_tasks = {declared_tasks} but tasks.jsonl has {n_tasks_lines} "
            f"line(s) ({n_tasks_unique} unique task string(s))",
        )
    else:
        sec.add(PASS, f"total_tasks = {declared_tasks} consistent with tasks.jsonl")

    # splits + videos are softer: stale values mislead but may be intentional
    splits = ds.info.get("splits") or {}
    train = splits.get("train")
    if train and n_ep:
        try:
            lo, hi = train.split(":")
            if int(hi) != n_ep:
                sec.add(WARN, f"splits.train = '{train}' but dataset has {n_ep} episodes (stale split?)")
            else:
                sec.add(PASS, f"splits.train = '{train}' covers all {n_ep} episodes")
        except ValueError:
            sec.add(WARN, f"splits.train = '{train}' is not in 'start:end' form")

    video_keys = [k for k, v in (ds.info.get("features") or {}).items() if v.get("dtype") == "video"]
    if video_keys:
        n_vid_files = sum(1 for _ in ds.root.glob("videos/chunk-*/*/episode_*.mp4"))
        declared_v = ds.info.get("total_videos")
        expected_v = len(video_keys) * n_ep
        if n_vid_files != expected_v:
            sec.add(WARN, f"{n_vid_files} video file(s) on disk, expected {expected_v} ({len(video_keys)} camera(s) x {n_ep} episodes)")
        elif declared_v != n_vid_files:
            sec.add(WARN, f"total_videos = {declared_v} but {n_vid_files} video file(s) on disk")
        else:
            sec.add(PASS, f"{n_vid_files} video file(s) on disk match {len(video_keys)} camera(s) x {n_ep} episodes")
    return sec


def check_global_index(ds) -> Section:
    """The global 'index' column must run 0..N-1 contiguously across
    episodes. A merge that copies files without rewriting it leaves each
    episode starting at 0 again."""
    sec = Section("Global frame index")
    if not ds.parquets:
        sec.add(WARN, "no parquet files; skipping")
        return sec
    seen = []
    for e_idx in sorted(ds.parquets):
        df = ds.read_parquet(e_idx)
        if "index" not in df.columns:
            sec.add(WARN, "no 'index' column; skipping")
            return sec
        seen.extend(int(v) for v in df["index"])
    expected = list(range(len(seen)))
    if seen == expected:
        sec.add(PASS, f"'index' runs 0..{len(seen)-1} contiguously across {len(ds.parquets)} episode(s)")
    else:
        # find the first break for a readable message
        first_bad = next((i for i, (a, b) in enumerate(zip(seen, expected)) if a != b), None)
        sec.add(
            FAIL,
            f"'index' is not contiguous: at global position {first_bad} found "
            f"{seen[first_bad]}, expected {expected[first_bad]} "
            "(a merge that copies parquet without rewriting 'index' causes this)",
        )
    return sec


def check_timestamps(ds, tolerance_s: float = 1e-4) -> Section:
    """Per-episode timestamps must be monotonic and consistent with fps.

    Note: lerobot itself hard-enforces the spacing at load time; this
    version is a dependency-free WARN so the report stays readable.
    """
    sec = Section("Timestamps")
    fps = (ds.info or {}).get("fps")
    if not fps or not ds.parquets:
        sec.add(WARN, "fps or parquet files missing; skipping")
        return sec
    step = 1.0 / fps
    bad = 0
    for e_idx in sorted(ds.parquets):
        ts = ds.read_parquet(e_idx)["timestamp"].tolist()
        if any(b < a for a, b in zip(ts, ts[1:])):
            sec.add(FAIL, f"episode {e_idx}: timestamps go backwards")
            bad += 1
            continue
        drift = [abs((b - a) - step) for a, b in zip(ts, ts[1:])]
        if drift and max(drift) > tolerance_s:
            sec.add(
                WARN,
                f"episode {e_idx}: worst frame-gap drift {max(drift)*1000:.2f} ms vs 1/fps "
                f"(tolerance {tolerance_s*1000:.2f} ms) -- dropped frames upstream?",
            )
            bad += 1
    if not bad:
        sec.add(PASS, f"all {len(ds.parquets)} episode(s) monotonic and within {tolerance_s*1000:.2f} ms of 1/fps")
    return sec


ALL_CHECKS = [
    check_stats_bijection,
    check_task_integrity,
    check_parquet_layout,
    check_info_totals,
    check_global_index,
    check_timestamps,
]
