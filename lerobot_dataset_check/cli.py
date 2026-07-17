"""CLI: python -m lerobot_dataset_check <dataset_dir> [<dataset_dir> ...]"""
from __future__ import annotations

import argparse
import sys

from . import checks, loaders, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="lerobot_dataset_check",
        description="Read-only integrity checks for LeRobot v2.1 datasets.",
    )
    parser.add_argument("datasets", nargs="+", help="one or more dataset directories")
    parser.add_argument(
        "--timestamp-tolerance-s",
        type=float,
        default=1e-4,
        help="allowed per-frame gap drift vs 1/fps (default 1e-4, matching lerobot)",
    )
    args = parser.parse_args(argv)

    any_fail = False
    for path in args.datasets:
        try:
            ds = loaders.open_dataset(path)
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

        version = (ds.info or {}).get("codebase_version", "<missing>")
        sections = []
        if version != "v2.1":
            sec = report.Section("Format version")
            sec.add(report.WARN, f"codebase_version is {version}; checks are written against v2.1")
            sections.append(sec)

        for fn in checks.ALL_CHECKS:
            if fn is checks.check_timestamps:
                sections.append(fn(ds, tolerance_s=args.timestamp_tolerance_s))
            else:
                sections.append(fn(ds))

        print(report.render(sections, header=f"dataset: {path}"))
        any_fail = any_fail or report.has_failure(sections)
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
