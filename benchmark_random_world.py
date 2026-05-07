#!/usr/bin/env python3
"""Benchmark short random-world task chains across multiple seeds."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from random_world_config import (
    RANDOM_WORLD_TASK_PRESET_NAMES,
    default_benchmark_artifacts_dir,
    default_benchmark_output,
    default_label_prefix,
    default_validation_ckpt_dir,
    default_validation_server_root,
    path_for_display,
    resolve_relative_path,
)


def resolve_python(root: Path) -> str:
    venv_python = root / "venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def summarize_results(
    results: list[dict],
    *,
    task_preset: str,
    mode: str,
    fallback_to_agent: bool,
    seed_count: int,
    duration_seconds: float,
) -> dict:
    successful = [
        entry for entry in results if isinstance(entry.get("result"), dict) and entry["result"].get("success")
    ]
    failure_phase_counts: dict[str, int] = {}
    failed_task_counts: dict[str, int] = {}
    total_fallback_count = 0
    duration_values: list[float] = []
    attempt_values: list[int] = []
    for entry in results:
        result = entry.get("result")
        if not isinstance(result, dict):
            continue
        failure_phase = result.get("failure_phase")
        if isinstance(failure_phase, str) and failure_phase:
            failure_phase_counts[failure_phase] = failure_phase_counts.get(failure_phase, 0) + 1
        failed_task = result.get("failed_task")
        if isinstance(failed_task, str) and failed_task:
            failed_task_counts[failed_task] = failed_task_counts.get(failed_task, 0) + 1
        total_fallback_count += int(result.get("fallback_count", 0) or 0)
        duration = result.get("duration_seconds")
        if isinstance(duration, (int, float)):
            duration_values.append(float(duration))
        attempt = result.get("attempt")
        if isinstance(attempt, int):
            attempt_values.append(attempt)
    return {
        "task_preset": task_preset,
        "mode": mode,
        "fallback_to_agent": fallback_to_agent,
        "seed_count": seed_count,
        "success_count": len(successful),
        "success_rate": len(successful) / seed_count if seed_count else 0,
        "duration_seconds": round(duration_seconds, 2),
        "total_fallback_count": total_fallback_count,
        "average_fallback_count": total_fallback_count / seed_count if seed_count else 0,
        "average_attempt": sum(attempt_values) / len(attempt_values) if attempt_values else 0,
        "average_run_duration_seconds": sum(duration_values) / len(duration_values) if duration_values else 0,
        "failure_phase_counts": failure_phase_counts,
        "failed_task_counts": failed_task_counts,
        "results": results,
    }


def resolve_benchmark_layout(
    root: Path,
    *,
    task_preset: str,
    label_prefix: str | None,
    output_json: str | None,
    artifacts_dir: str | None,
    ckpt_dir: str | None,
    server_root: str | None,
) -> tuple[str, Path, Path, Path, Path]:
    resolved_label_prefix = label_prefix or default_label_prefix(task_preset)
    resolved_output = resolve_relative_path(
        root,
        output_json or default_benchmark_output(task_preset, label_prefix=resolved_label_prefix),
    ).resolve()
    resolved_artifacts_dir = resolve_relative_path(
        root,
        artifacts_dir or default_benchmark_artifacts_dir(task_preset, label_prefix=resolved_label_prefix),
    ).resolve()
    resolved_ckpt_dir = (
        resolve_relative_path(root, ckpt_dir).resolve()
        if ckpt_dir
        else (root / default_validation_ckpt_dir(f"{resolved_label_prefix}_benchmark")).resolve()
    )
    resolved_server_root = (
        resolve_relative_path(root, server_root).resolve()
        if server_root
        else (root / default_validation_server_root(f"{resolved_label_prefix}_benchmark")).resolve()
    )
    return (
        resolved_label_prefix,
        resolved_output,
        resolved_artifacts_dir,
        resolved_ckpt_dir,
        resolved_server_root,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seeds",
        nargs="+",
        required=True,
        help="Seed list to benchmark",
    )
    parser.add_argument(
        "--task-preset",
        choices=RANDOM_WORLD_TASK_PRESET_NAMES,
        default="short-random",
        help="Built-in random-world task chain passed through to validate_random_world.py",
    )
    parser.add_argument(
        "--mode",
        choices=("agent", "direct"),
        default="agent",
        help="Validation mode passed through to validate_random_world.py",
    )
    parser.add_argument(
        "--fallback-to-agent",
        action="store_true",
        help="Allow direct mode to fall back to agent mode per task",
    )
    parser.add_argument(
        "--output-json",
        help="Where to write the benchmark summary JSON",
    )
    parser.add_argument(
        "--label-prefix",
        help="Prefix used for per-seed labels and JSON outputs",
    )
    parser.add_argument(
        "--artifacts-dir",
        help="Directory used for per-seed JSON outputs and validation logs",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=600,
        help="Per-seed timeout passed to validate_random_world.py",
    )
    parser.add_argument(
        "--ckpt-dir",
        help="Optional isolated checkpoint dir shared by this benchmark run",
    )
    parser.add_argument(
        "--server-root",
        help="Optional isolated server root shared by this benchmark run",
    )
    parser.add_argument(
        "--mc-port",
        type=int,
        default=25565,
        help="Minecraft server port passed through to validate_random_world.py",
    )
    parser.add_argument(
        "--bridge-port",
        type=int,
        default=3000,
        help="Mineflayer bridge HTTP port passed through to validate_random_world.py",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parent
    python_executable = resolve_python(root)
    label_prefix, output_path, artifacts_root, ckpt_path, server_root = resolve_benchmark_layout(
        root,
        task_preset=args.task_preset,
        label_prefix=args.label_prefix,
        output_json=args.output_json,
        artifacts_dir=args.artifacts_dir,
        ckpt_dir=args.ckpt_dir,
        server_root=args.server_root,
    )
    artifacts_root.mkdir(parents=True, exist_ok=True)
    results = []
    started_at = time.monotonic()
    for seed in args.seeds:
        seed_output_path = artifacts_root / f"{label_prefix}-{seed}.json"
        command = [
            python_executable,
            "validate_random_world.py",
            "--seed",
            seed,
            "--task-preset",
            args.task_preset,
            "--label",
            f"{label_prefix}-{seed}",
            "--mode",
            args.mode,
            "--ckpt-dir",
            str(ckpt_path),
            "--server-root",
            str(server_root),
            "--artifacts-dir",
            str(artifacts_root),
            "--timeout-seconds",
            str(args.timeout_seconds),
            "--mc-port",
            str(args.mc_port),
            "--bridge-port",
            str(args.bridge_port),
            "--output-json",
            str(seed_output_path),
        ]
        if args.fallback_to_agent:
            command.append("--fallback-to-agent")
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        entry = {
            "seed": seed,
            "output_json": path_for_display(root, seed_output_path),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode == 0:
            try:
                entry["result"] = json.loads(completed.stdout)
            except json.JSONDecodeError:
                entry["result"] = None
        else:
            entry["result"] = None
        results.append(entry)

    summary = summarize_results(
        results,
        task_preset=args.task_preset,
        mode=args.mode,
        fallback_to_agent=args.fallback_to_agent,
        seed_count=len(args.seeds),
        duration_seconds=time.monotonic() - started_at,
    )
    summary.update(
        {
            "label_prefix": label_prefix,
            "artifacts_dir": path_for_display(root, artifacts_root),
            "mc_port": args.mc_port,
            "bridge_port": args.bridge_port,
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
