#!/usr/bin/env python3
"""Verify random-world JSON summaries and recorded videos."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from random_world_config import path_for_display, resolve_relative_path


DEFAULT_JSON_ARTIFACTS = [
    "recordings/random-world-benchmark-20seeds-v2.json",
    "recordings/random-world-long-benchmark-10seeds-v2.json",
    "recordings/random-world-woodpick-12346-v2.json",
]

DEFAULT_VIDEO_ARTIFACTS = [
    "recordings/random-world-demo.mp4",
    "recordings/random-world-long-demo.mp4",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        dest="json_paths",
        action="append",
        default=[],
        help="JSON artifact to verify; repeat to check multiple files",
    )
    parser.add_argument(
        "--video",
        dest="video_paths",
        action="append",
        default=[],
        help="Video artifact to run through ffmpeg blackdetect; repeat to check multiple files",
    )
    parser.add_argument(
        "--blackdetect-duration",
        type=float,
        default=0.1,
        help="blackdetect d= threshold in seconds",
    )
    parser.add_argument(
        "--blackdetect-threshold",
        type=float,
        default=0.98,
        help="blackdetect pic_th threshold",
    )
    return parser


def resolve_requested_paths(root: Path, explicit_paths: list[str], defaults: list[str], *, any_explicit: bool) -> list[Path]:
    selected = explicit_paths if explicit_paths else ([] if any_explicit else defaults)
    return [resolve_relative_path(root, path).resolve() for path in selected]


def verify_json_artifact(root: Path, path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"{path_for_display(root, path)} is not a JSON object")

    if "seed_count" in data and "success_count" in data:
        seed_count = int(data["seed_count"])
        success_count = int(data["success_count"])
        if success_count != seed_count:
            raise RuntimeError(
                f"{path_for_display(root, path)} benchmark is incomplete: {success_count}/{seed_count} succeeded"
            )
        return f"benchmark ok ({success_count}/{seed_count})"

    if "success" in data:
        if not bool(data["success"]):
            failed = data.get("failed")
            raise RuntimeError(
                f"{path_for_display(root, path)} validation did not succeed; failed={failed!r}"
            )
        tasks = data.get("tasks") or []
        completed = data.get("completed") or []
        failed = data.get("failed") or []
        if failed:
            raise RuntimeError(
                f"{path_for_display(root, path)} reports success but still lists failed tasks: {failed!r}"
            )
        if tasks and len(completed) != len(tasks):
            raise RuntimeError(
                f"{path_for_display(root, path)} completed {len(completed)}/{len(tasks)} tasks"
            )
        return f"validation ok ({len(completed)}/{len(tasks) or len(completed)} tasks)"

    raise RuntimeError(f"{path_for_display(root, path)} does not match a supported artifact schema")


def verify_video_artifact(root: Path, path: Path, *, blackdetect_duration: float, blackdetect_threshold: float) -> str:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(path),
        "-vf",
        f"blackdetect=d={blackdetect_duration}:pic_th={blackdetect_threshold}",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"ffmpeg blackdetect failed for {path_for_display(root, path)}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    blackdetect_output = f"{completed.stdout}\n{completed.stderr}"
    if "black_start:" in blackdetect_output:
        raise RuntimeError(f"blackdetect found black frames in {path_for_display(root, path)}")
    return "video ok (no blackdetect segments)"


def main() -> int:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parent
    any_explicit = bool(args.json_paths or args.video_paths)
    json_paths = resolve_requested_paths(root, args.json_paths, DEFAULT_JSON_ARTIFACTS, any_explicit=any_explicit)
    video_paths = resolve_requested_paths(root, args.video_paths, DEFAULT_VIDEO_ARTIFACTS, any_explicit=any_explicit)

    if not json_paths and not video_paths:
        raise RuntimeError("No artifacts selected for verification")

    for path in [*json_paths, *video_paths]:
        if not path.exists():
            raise RuntimeError(f"Artifact not found: {path_for_display(root, path)}")

    for path in json_paths:
        result = verify_json_artifact(root, path)
        print(f"JSON  {path_for_display(root, path)}: {result}")
    for path in video_paths:
        result = verify_video_artifact(
            root,
            path,
            blackdetect_duration=args.blackdetect_duration,
            blackdetect_threshold=args.blackdetect_threshold,
        )
        print(f"VIDEO {path_for_display(root, path)}: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
