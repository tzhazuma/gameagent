#!/usr/bin/env python3
"""Run a random-world validation sequence and print a compact summary."""

from __future__ import annotations

import argparse
import json
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

from random_world_config import (
    RANDOM_WORLD_TASK_PRESET_NAMES,
    default_validation_ckpt_dir,
    default_validation_server_root,
    get_random_world_tasks,
    path_for_display,
    resolve_relative_path,
)


def classify_failure_phase(tasks: list[str], completed: list[str], failed: list[str], error: str | None) -> str:
    if error == "server_ready_timeout":
        return "server"
    if failed:
        failed_task = failed[0]
        failed_index = len(completed)
        if failed_index == 0:
            if error and "spawn" in error:
                return "spawn"
            return "task_1"
        if failed_task == "Mine 1 wood log" and failed_index == 2:
            return "mine_log_second"
        if failed_task == "Mine 1 wood log" and failed_index == 4:
            return "mine_log_third"
        if failed_task == "Mine 1 wood log":
            return "mine_log"
        if failed_task == "Craft 1 crafting_table":
            return "craft_table"
        if failed_task == "Craft 4 sticks":
            return "craft_sticks"
        if failed_task == "Craft 1 wooden_pickaxe":
            return "craft_wooden_pickaxe"
        return failed_task.replace(" ", "_").lower()
    if error and "spawn" in error:
        return "spawn"
    if len(completed) == len(tasks):
        return "completed"
    return "unknown"


def summarize_metrics(result: dict, tasks: list[str]) -> dict:
    completed = result.get("completed", [])
    failed = result.get("failed", [])
    error = result.get("error")
    failure_reason = result.get("failure_reason")
    if failure_reason is None and error is not None:
        failure_reason = error
    return {
        "failed_task": failed[0] if failed else None,
        "failure_reason": failure_reason,
        "failure_phase": classify_failure_phase(tasks, completed, failed, error),
        "used_fallback_on_tasks": result.get("used_fallback_on_tasks", []),
        "fallback_events": result.get("fallback_events", []),
        "task_outcomes": result.get("task_outcomes", []),
        "fallback_count": int(result.get("fallback_count", 0) or 0),
        "spawn_screening_required": bool(result.get("spawn_screening_required", False)),
        "spawn_screening_success": bool(result.get("spawn_screening_success", False)),
        "spawn_screening_attempts": int(result.get("spawn_screening_attempts", 0) or 0),
        "spawn_screening_nearby_tree_initial": bool(result.get("spawn_screening_nearby_tree_initial", False)),
        "duration_seconds": float(result.get("duration_seconds", 0) or 0),
    }


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

    extra_metrics = {
        key: value
        for key, value in result.items()
        if key not in {"completed", "failed", "error", "interrupted"}
    }

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
        **extra_metrics,
    }


def resolve_validation_layout(
    root: Path,
    *,
    label: str,
    artifacts_dir: str,
    ckpt_dir: str | None,
    server_root: str | None,
) -> tuple[Path, Path, Path, Path, Path]:
    artifacts_root = resolve_relative_path(root, artifacts_dir).resolve()
    ckpt_path = (
        resolve_relative_path(root, ckpt_dir).resolve()
        if ckpt_dir
        else (root / default_validation_ckpt_dir(label)).resolve()
    )
    resolved_server_root = (
        resolve_relative_path(root, server_root).resolve()
        if server_root
        else (root / default_validation_server_root(label)).resolve()
    )
    return (
        artifacts_root,
        ckpt_path,
        resolved_server_root,
        artifacts_root / f"{label}.done",
        resolved_server_root / "ready.json",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", help="Optional random-world seed")
    parser.add_argument(
        "--server-root",
        help="Optional isolated server root for this validation run",
    )
    parser.add_argument(
        "--task-preset",
        choices=RANDOM_WORLD_TASK_PRESET_NAMES,
        default="short-random",
        help="Built-in random-world task chain to validate",
    )
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
        help="Optional checkpoint directory for the validation run; defaults to a label-derived path",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="recordings",
        help="Directory used for validation logs, done files, and optional JSON output",
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
    parser.add_argument(
        "--mc-port",
        type=int,
        default=25565,
        help="Minecraft server port used for start_demo_server.py and run_recorded_demo.py",
    )
    parser.add_argument(
        "--bridge-port",
        type=int,
        default=3000,
        help="Mineflayer bridge HTTP port passed through to run_recorded_demo.py",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parent
    python_executable = resolve_python(root)
    tasks = get_random_world_tasks(args.task_preset)
    artifacts_root, ckpt_path, server_root, done_file, ready_file = resolve_validation_layout(
        root,
        label=args.label,
        artifacts_dir=args.artifacts_dir,
        ckpt_dir=args.ckpt_dir,
        server_root=args.server_root,
    )
    artifacts_root.mkdir(parents=True, exist_ok=True)
    server_log = artifacts_root / f"{args.label}-server.log"
    run_log = artifacts_root / f"{args.label}-run.log"

    for path in (ready_file, done_file, server_log, run_log):
        if path.exists():
            path.unlink()
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
                    "--port",
                    str(args.mc_port),
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
                    "task_preset": args.task_preset,
                    "tasks": tasks,
                    "completed": [],
                    "failed": [tasks[0]],
                    "success": False,
                    "mc_port": args.mc_port,
                    "bridge_port": args.bridge_port,
                    "artifacts_dir": path_for_display(root, artifacts_root),
                    "server_log": path_for_display(root, server_log),
                    "run_log": path_for_display(root, run_log),
                    "error": "server_ready_timeout",
                }
                final_summary.update(
                    {
                        "failed_task": tasks[0],
                        "failure_reason": "server_ready_timeout",
                        "failure_phase": "server",
                        "used_fallback_on_tasks": [],
                        "fallback_events": [],
                        "task_outcomes": [],
                        "fallback_count": 0,
                        "spawn_screening_required": False,
                        "spawn_screening_success": False,
                        "spawn_screening_attempts": 0,
                        "spawn_screening_nearby_tree_initial": False,
                        "duration_seconds": 0.0,
                    }
                )
                if attempt == args.max_attempts:
                    break
                continue

            with open(run_log, "w", encoding="utf-8") as handle:
                run_command = [
                    python_executable,
                    "run_recorded_demo.py",
                    str(args.mc_port),
                    "--mode",
                    args.mode,
                    "--ckpt-dir",
                    str(ckpt_path),
                    "--server-port",
                    str(args.bridge_port),
                    "--start-from-ready-file",
                    str(ready_file),
                    "--spawn-from-world",
                    "--done-file",
                    str(done_file),
                    "--reset-mode",
                    "soft",
                    "--tasks",
                    *tasks,
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
                tasks,
                timed_out=timed_out,
                return_code=return_code,
            )
            completed = result.get("completed", [])
            failed = result.get("failed", [])
            success = len(completed) == len(tasks) and not failed and not timed_out and return_code in (0, None)

            final_summary = {
                "seed": args.seed,
                "label": args.label,
                "task_preset": args.task_preset,
                "mode": args.mode,
                "fallback_to_agent": args.fallback_to_agent,
                "timed_out": timed_out,
                "timeout_seconds": args.timeout_seconds,
                "attempt": attempt,
                "max_attempts": args.max_attempts,
                "tasks": tasks,
                "completed": completed,
                "failed": failed,
                "success": success,
                "mc_port": args.mc_port,
                "bridge_port": args.bridge_port,
                "artifacts_dir": path_for_display(root, artifacts_root),
                "server_log": path_for_display(root, server_log),
                "run_log": path_for_display(root, run_log),
                "returncode": return_code,
                "interrupted": result.get("interrupted", False),
            }
            if result.get("error"):
                final_summary["error"] = result["error"]
            final_summary.update(summarize_metrics(result, tasks))
            if success or (failed and failed[0] != tasks[0]) or attempt == args.max_attempts:
                break
        finally:
            interrupt_process(run_proc)
            interrupt_process(server_proc)
            time.sleep(2)

    if final_summary is None:
        final_summary = {
            "seed": args.seed,
            "label": args.label,
            "task_preset": args.task_preset,
            "mode": args.mode,
            "fallback_to_agent": args.fallback_to_agent,
            "timed_out": False,
            "timeout_seconds": args.timeout_seconds,
            "attempt": args.max_attempts,
            "max_attempts": args.max_attempts,
            "tasks": tasks,
            "completed": [],
            "failed": [tasks[0]],
            "success": False,
            "mc_port": args.mc_port,
            "bridge_port": args.bridge_port,
            "artifacts_dir": path_for_display(root, artifacts_root),
            "server_log": path_for_display(root, server_log),
            "run_log": path_for_display(root, run_log),
        }
        final_summary.update(
            {
                "failed_task": tasks[0],
                "failure_reason": None,
                "failure_phase": "task_1",
                "used_fallback_on_tasks": [],
                "fallback_events": [],
                "task_outcomes": [],
                "fallback_count": 0,
                "spawn_screening_required": False,
                "spawn_screening_success": False,
                "spawn_screening_attempts": 0,
                "spawn_screening_nearby_tree_initial": False,
                "duration_seconds": 0.0,
            }
        )
    if args.output_json:
        output_path = resolve_relative_path(root, args.output_json).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(final_summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final_summary, indent=2))


if __name__ == "__main__":
    main()
