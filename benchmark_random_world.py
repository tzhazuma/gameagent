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
        choices=("short-random", "long-random"),
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
        "random-world" if args.task_preset == "short-random" else "random-world-long"
    )
    output_json = args.output_json or f"recordings/{label_prefix}-benchmark.json"
    ckpt_dir = args.ckpt_dir or f"ckpt_{label_prefix.replace('-', '_')}_validation"
    server_root = args.server_root or f".demo_server_{label_prefix.replace('-', '_')}_validation"
    results = []
    started_at = time.time()
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
    summary = {
        "task_preset": args.task_preset,
        "mode": args.mode,
        "fallback_to_agent": args.fallback_to_agent,
        "seed_count": len(args.seeds),
        "success_count": len(successful),
        "success_rate": len(successful) / len(args.seeds) if args.seeds else 0,
        "duration_seconds": round(time.time() - started_at, 2),
        "results": results,
    }
    output_path = (root / output_json).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
