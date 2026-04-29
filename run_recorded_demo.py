#!/usr/bin/env python3
"""Run a short deterministic Voyager session for recording."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


DEFAULT_TASKS = [
    "Mine 3 spruce_log",
    "Craft 8 spruce_planks",
    "Craft 1 crafting_table",
    "Craft 1 wooden_pickaxe",
    "Mine 3 cobblestone",
]
DEFAULT_POSITION = {"x": 0.5, "y": 81.0, "z": 0.5}


def load_local_env(file_name: str = ".env.local") -> None:
    env_path = Path(__file__).resolve().with_name(file_name)
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or key in os.environ:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ[key] = value


def clear_proxy_env() -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(key, None)


def parse_position(value: str) -> dict[str, float]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("position must be x,y,z")
    try:
        x, y, z = (float(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("position must contain numeric x,y,z") from exc
    return {"x": x, "y": y, "z": z}


def parse_inventory(value: str) -> dict[str, int]:
    try:
        inventory = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("inventory must be valid JSON") from exc
    if not isinstance(inventory, dict):
        raise argparse.ArgumentTypeError("inventory must decode to an object")
    normalized = {}
    for key, amount in inventory.items():
        if not isinstance(key, str):
            raise argparse.ArgumentTypeError("inventory keys must be strings")
        if not isinstance(amount, int):
            raise argparse.ArgumentTypeError("inventory values must be integers")
        normalized[key] = amount
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", type=int, nargs="?", default=25565, help="Minecraft server port")
    parser.add_argument(
        "--ckpt-dir",
        default="ckpt_recorded_demo",
        help="Checkpoint directory for the recorded run",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=3000,
        help="Mineflayer bridge HTTP port",
    )
    parser.add_argument(
        "--skill-library-dir",
        default="ckpt_voyager",
        help="Existing skill library used for retrieval only",
    )
    parser.add_argument(
        "--position",
        type=parse_position,
        default=DEFAULT_POSITION,
        help="Spawn position as x,y,z",
    )
    parser.add_argument(
        "--inventory",
        type=parse_inventory,
        default={},
        help="Initial inventory JSON for the hard reset",
    )
    parser.add_argument(
        "--reset-mode",
        choices=("soft", "hard"),
        default="soft",
        help="Environment reset mode used before the scripted run",
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=DEFAULT_TASKS,
        help="Ordered task sequence to run",
    )
    return parser


load_local_env()
clear_proxy_env()

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

if not os.environ.get("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY must be set in the environment")

os.environ.setdefault("OPENAI_API_BASE", "https://opencode.ai/zen/go/v1")

import voyager.utils as U
from voyager import Voyager


def main() -> None:
    args = build_parser().parse_args()
    model_name = os.environ.get("VOYAGER_MODEL_NAME", "kimi-k2.6")

    print("=" * 60)
    print("VOYAGER RECORDED DEMO")
    print("=" * 60)
    print(f"Minecraft port: {args.port}")
    print(f"Checkpoint dir: {args.ckpt_dir}")
    print(f"Skill library: {args.skill_library_dir}")
    print(f"Viewer port: {os.environ.get('VOYAGER_VIEWER_PORT', 'disabled')}")
    print(f"Start position: {args.position}")
    print("Task sequence:")
    for index, task in enumerate(args.tasks, start=1):
        print(f"  {index}. {task}")
    print("=" * 60)

    voyager = Voyager(
        mc_port=args.port,
        server_port=args.server_port,
        openai_api_key=os.environ["OPENAI_API_KEY"],
        openai_api_base=os.environ["OPENAI_API_BASE"],
        action_agent_model_name=model_name,
        curriculum_agent_model_name=model_name,
        curriculum_agent_qa_model_name=model_name,
        critic_agent_model_name=model_name,
        skill_manager_model_name=model_name,
        ckpt_dir=args.ckpt_dir,
        skill_library_dir=args.skill_library_dir,
        resume=False,
        max_iterations=len(args.tasks),
        env_wait_ticks=20,
        env_request_timeout=300,
        openai_api_request_timeout=240,
    )

    try:
        qa_cache_path = Path(args.skill_library_dir) / "curriculum" / "qa_cache.json"
        if qa_cache_path.exists():
            voyager.curriculum_agent.qa_cache = U.load_json(str(qa_cache_path))

        voyager.curriculum_agent.completed_tasks = []
        voyager.curriculum_agent.failed_tasks = []
        reset_options = {
            "mode": args.reset_mode,
            "wait_ticks": voyager.env_wait_ticks,
            "position": args.position,
        }
        if args.reset_mode == "hard" and args.inventory:
            reset_options["inventory"] = args.inventory
        voyager.last_events = voyager.env.reset(
            options=reset_options
        )

        results = []
        for task in args.tasks:
            context = voyager.curriculum_agent.get_task_context(task)
            try:
                _, _, _, info = voyager.rollout(
                    task=task,
                    context=context,
                    reset_env=False,
                )
            except Exception as exc:
                info = {
                    "task": task,
                    "success": False,
                    "error": str(exc),
                }
            results.append(info)
            voyager.curriculum_agent.update_exploration_progress(info)
            if not info["success"]:
                break

        completed = [item["task"] for item in results if item["success"]]
        failed = [item["task"] for item in results if not item["success"]]

        print("\n" + "=" * 60)
        print("RECORDED DEMO COMPLETE")
        print("=" * 60)
        print(f"Completed tasks: {completed}")
        print(f"Failed tasks: {failed}")
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        voyager.close()
        print("Voyager closed.")


if __name__ == "__main__":
    main()
