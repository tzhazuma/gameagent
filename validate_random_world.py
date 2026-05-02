#!/usr/bin/env python3
"""Run a short random-world validation sequence and print a compact summary."""

from __future__ import annotations

import argparse
import json
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path


SHORT_TASKS = [
    "Mine 1 wood log",
    "Craft 1 crafting_table",
]


def resolve_python(root: Path) -> str:
    venv_python = root / "venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def wait_for_file(path: Path, timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {path}")


def interrupt_process(process: subprocess.Popen[str] | None, timeout: int = 30) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def load_run_result(
    done_file: Path,
    tasks: list[str],
    *,
    timed_out: bool,
    return_code: int | None,
) -> dict:
    if done_file.exists():
        try:
            result = json.loads(done_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result = {
                "completed": [],
                "failed": [],
                "error": f"invalid_done_file: {exc}",
            }
    else:
        result = {}

    completed = result.get("completed", [])
    failed = result.get("failed", [])
    if not isinstance(completed, list):
        completed = []
    if not isinstance(failed, list):
        failed = []

    error = result.get("error")
    if error is not None:
        error = str(error)
    interrupted = bool(result.get("interrupted"))

    if timed_out and len(completed) < len(tasks) and not failed:
        failed = [tasks[len(completed)]]
        error = error or "timeout"
    if return_code not in (0, None) and len(completed) < len(tasks) and not failed:
        failed = [tasks[len(completed)]]
    if return_code not in (0, None) and error is None:
        error = f"run_exit_{return_code}"

    return {
        "completed": completed,
        "failed": failed,
        "error": error,
        "interrupted": interrupted,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", help="Optional random-world seed")
    parser.add_argument(
        "--mode",
        choices=("agent", "direct"),
        default="agent",
        help="Task execution mode for the short validation run",
    )
    parser.add_argument(
        "--fallback-to-agent",
        action="store_true",
        help="Allow direct mode to fall back to the agent per task",
    )
    parser.add_argument(
        "--ckpt-dir",
        default="ckpt_random_world_validation",
        help="Checkpoint directory for the validation run",
    )
    parser.add_argument(
        "--output-json",
        help="Optional path to write the final summary JSON",
    )
    parser.add_argument(
        "--label",
        default="random-world-validation",
        help="Prefix used for log and done-file names under recordings/",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=600,
        help="Maximum run time for run_recorded_demo.py before marking the validation as timed out",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="How many fresh world attempts to try before giving up on this seed",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parent
    python_executable = resolve_python(root)
    server_root = root / ".demo_server_random_validation"
    ready_file = server_root / "ready.json"
    recordings_root = root / "recordings"
    done_file = recordings_root / f"{args.label}.done"
    server_log = recordings_root / f"{args.label}-server.log"
    run_log = recordings_root / f"{args.label}-run.log"

    for path in (ready_file, done_file, server_log, run_log):
        if path.exists():
            path.unlink()
    ckpt_path = root / args.ckpt_dir
    if ckpt_path.exists():
        shutil.rmtree(ckpt_path, ignore_errors=True)

    final_summary = None
    for attempt in range(1, args.max_attempts + 1):
        server_proc = None
        run_proc = None
        timed_out = False
        try:
            for path in (ready_file, done_file):
                if path.exists():
                    path.unlink()
            with open(server_log, "w", encoding="utf-8") as handle:
                server_command = [
                    python_executable,
                    "start_demo_server.py",
                    "--fresh-world",
                    "--root",
                    str(server_root),
                    "--ready-file",
                    str(ready_file),
                    "--world-type",
                    "minecraft:normal",
                    "--no-demo-arena",
                ]
                if args.seed:
                    server_command.extend(["--seed", args.seed])
                server_proc = subprocess.Popen(
                    server_command,
                    cwd=root,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            try:
                wait_for_file(ready_file, 180)
            except RuntimeError:
                final_summary = {
                    "seed": args.seed,
                    "label": args.label,
                    "mode": args.mode,
                    "fallback_to_agent": args.fallback_to_agent,
                    "timed_out": False,
                    "timeout_seconds": args.timeout_seconds,
                    "attempt": attempt,
                    "max_attempts": args.max_attempts,
                    "tasks": SHORT_TASKS,
                    "completed": [],
                    "failed": [SHORT_TASKS[0]],
                    "success": False,
                    "server_log": str(server_log.relative_to(root)),
                    "run_log": str(run_log.relative_to(root)),
                    "error": "server_ready_timeout",
                }
                if attempt == args.max_attempts:
                    break
                continue

            with open(run_log, "w", encoding="utf-8") as handle:
                run_command = [
                    python_executable,
                    "run_recorded_demo.py",
                    "25565",
                    "--mode",
                    args.mode,
                    "--ckpt-dir",
                    args.ckpt_dir,
                    "--start-from-ready-file",
                    str(ready_file),
                    "--spawn-from-world",
                    "--done-file",
                    str(done_file),
                    "--reset-mode",
                    "soft",
                    "--tasks",
                    *SHORT_TASKS,
                ]
                if args.fallback_to_agent:
                    run_command.append("--fallback-to-agent")
                run_proc = subprocess.Popen(
                    run_command,
                    cwd=root,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            try:
                return_code = run_proc.wait(timeout=args.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                interrupt_process(run_proc)
                return_code = run_proc.returncode if run_proc is not None else 1

            result = load_run_result(
                done_file,
                SHORT_TASKS,
                timed_out=timed_out,
                return_code=return_code,
            )
            completed = result.get("completed", [])
            failed = result.get("failed", [])
            success = len(completed) == len(SHORT_TASKS) and not failed and not timed_out and return_code in (0, None)

            final_summary = {
                "seed": args.seed,
                "label": args.label,
                "mode": args.mode,
                "fallback_to_agent": args.fallback_to_agent,
                "timed_out": timed_out,
                "timeout_seconds": args.timeout_seconds,
                "attempt": attempt,
                "max_attempts": args.max_attempts,
                "tasks": SHORT_TASKS,
                "completed": completed,
                "failed": failed,
                "success": success,
                "server_log": str(server_log.relative_to(root)),
                "run_log": str(run_log.relative_to(root)),
                "returncode": return_code,
                "interrupted": result.get("interrupted", False),
            }
            if result.get("error"):
                final_summary["error"] = result["error"]
            if success or (failed and failed[0] != SHORT_TASKS[0]) or attempt == args.max_attempts:
                break
        finally:
            interrupt_process(run_proc)
            interrupt_process(server_proc)
            time.sleep(2)

    if final_summary is None:
        final_summary = {
            "seed": args.seed,
            "label": args.label,
            "mode": args.mode,
            "fallback_to_agent": args.fallback_to_agent,
            "timed_out": False,
            "timeout_seconds": args.timeout_seconds,
            "attempt": args.max_attempts,
            "max_attempts": args.max_attempts,
            "tasks": SHORT_TASKS,
            "completed": [],
            "failed": [SHORT_TASKS[0]],
            "success": False,
            "server_log": str(server_log.relative_to(root)),
            "run_log": str(run_log.relative_to(root)),
        }
    if args.output_json:
        output_path = (root / args.output_json).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(final_summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final_summary, indent=2))


if __name__ == "__main__":
    main()
