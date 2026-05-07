#!/usr/bin/env python3
"""Benchmark short random-world task chains across multiple seeds."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def resolve_python(root: Path) -> str:
    venv_python = root / "venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


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
        choices=("short-random", "long-random", "woodpick-random"),
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parent
    python_executable = resolve_python(root)
    label_prefix = args.label_prefix or (
        "random-world"
        if args.task_preset == "short-random"
        else "random-world-long"
        if args.task_preset == "long-random"
        else "random-world-woodpick"
    )
    output_json = args.output_json or f"recordings/{label_prefix}-benchmark.json"
    ckpt_dir = args.ckpt_dir or f"ckpt_{label_prefix.replace('-', '_')}_validation"
    server_root = args.server_root or f".demo_server_{label_prefix.replace('-', '_')}_validation"
    results = []
    started_at = time.monotonic()
    for seed in args.seeds:
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
            ckpt_dir,
            "--server-root",
            server_root,
            "--timeout-seconds",
            str(args.timeout_seconds),
            "--output-json",
            f"recordings/{label_prefix}-{seed}.json",
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
    summary = {
        "task_preset": args.task_preset,
        "mode": args.mode,
        "fallback_to_agent": args.fallback_to_agent,
        "seed_count": len(args.seeds),
        "success_count": len(successful),
        "success_rate": len(successful) / len(args.seeds) if args.seeds else 0,
        "duration_seconds": round(time.monotonic() - started_at, 2),
        "total_fallback_count": total_fallback_count,
        "average_fallback_count": total_fallback_count / len(args.seeds) if args.seeds else 0,
        "average_attempt": sum(attempt_values) / len(attempt_values) if attempt_values else 0,
        "average_run_duration_seconds": sum(duration_values) / len(duration_values) if duration_values else 0,
        "failure_phase_counts": failure_phase_counts,
        "failed_task_counts": failed_task_counts,
        "results": results,
    }
    output_path = (root / output_json).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
