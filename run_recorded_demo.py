#!/usr/bin/env python3
"""Run a scripted Voyager session for recording or evaluation."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable


DEFAULT_TASKS = [
    "Mine 3 spruce_log",
    "Craft 8 spruce_planks",
    "Craft 1 crafting_table",
    "Craft 4 sticks",
    "Craft 4 spruce_planks",
    "Craft 1 wooden_pickaxe",
    "Mine 3 cobblestone",
    "Craft 1 stone_pickaxe",
    "Mine 8 cobblestone",
    "Craft 1 furnace",
]
DEFAULT_POSITION = {"x": 0.5, "y": 81.0, "z": 0.5}
TASK_TO_SKILL = {
    "Mine 1 wood log": "mineWoodLog",
    "Mine 3 spruce_log": "mineThreeSpruceLogs",
    "Craft 4 spruce_planks": "craftSprucePlanks",
    "Craft 8 spruce_planks": "craftEightSprucePlanks",
    "Craft 1 crafting_table": "craftCraftingTable",
    "Craft 4 sticks": "craftFourSticks",
    "Craft 1 wooden_pickaxe": "craftWoodenPickaxe",
    "Mine 3 cobblestone": "mineThreeCobblestone",
    "Craft 1 stone_pickaxe": "craftStonePickaxe",
    "Mine 8 cobblestone": "mineEightCobblestone",
    "Craft 1 furnace": "craftFurnace",
}
WOOD_LOG_NAMES = [
    "oak_log",
    "birch_log",
    "spruce_log",
    "jungle_log",
    "acacia_log",
    "dark_oak_log",
    "mangrove_log",
]
WOOD_PLANK_NAMES = [
    "oak_planks",
    "birch_planks",
    "spruce_planks",
    "jungle_planks",
    "acacia_planks",
    "dark_oak_planks",
    "mangrove_planks",
]
TASK_ITEM_ALIASES = {
    "sticks": "stick",
}
DIRECT_SKILL_OVERRIDES = {
    "mineWoodLog": """
async function mineWoodLog(bot) {
  const logNames = ["oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log", "dark_oak_log", "mangrove_log"];
  const initialLogCount = logNames.reduce((total, name) => {
    const item = mcData.itemsByName[name];
    if (!item) return total;
    const invItem = bot.inventory.findInventoryItem(item.id);
    return total + (invItem ? invItem.count : 0);
  }, 0);

  function findNearbyLogBlock() {
    for (const name of logNames) {
      const blockId = mcData.blocksByName[name]?.id;
      if (!blockId) continue;
      const block = bot.findBlock({
        matching: blockId,
        maxDistance: 32,
      });
      if (block) {
        return block;
      }
    }
    return null;
  }

  let targetBlock = findNearbyLogBlock();
  if (!targetBlock) {
    bot.chat("No wood log nearby, exploring...");
    const directions = [new Vec3(1, 0, 1), new Vec3(1, 0, -1), new Vec3(-1, 0, 1), new Vec3(-1, 0, -1), new Vec3(1, 0, 0), new Vec3(-1, 0, 0), new Vec3(0, 0, 1), new Vec3(0, 0, -1)];
    targetBlock = await exploreUntil(bot, directions[Math.floor(Math.random() * directions.length)], 60, () => findNearbyLogBlock());
  }

  if (!targetBlock) {
    bot.chat("Could not find any wood log.");
    return;
  }

  bot.chat(`Mining 1 ${targetBlock.name}...`);
  await mineBlock(bot, targetBlock.name, 1);
  const finalLogCount = logNames.reduce((total, name) => {
    const item = mcData.itemsByName[name];
    if (!item) return total;
    const invItem = bot.inventory.findInventoryItem(item.id);
    return total + (invItem ? invItem.count : 0);
  }, 0);
  bot.chat(`Finished mining 1 wood log. Inventory logs: ${initialLogCount} -> ${finalLogCount}.`);
}
""",
    "craftFourSticks": """
async function craftFourSticks(bot) {
  async function craftInventoryItem(bot, name, count = 1) {
    const item = mcData.itemsByName[name];
    if (!item) {
      throw new Error(`Unknown item: ${name}`);
    }
    const recipe = bot.recipesFor(item.id, null, 1, null)[0];
    if (!recipe) {
      throw new Error(`No inventory crafting recipe found for ${name}`);
    }
    await bot.craft(recipe, count, null);
  }

  const stickItem = mcData.itemsByName["stick"];
  const currentSticks = bot.inventory.findInventoryItem(stickItem.id);
  if (currentSticks && currentSticks.count >= 4) {
    bot.chat(`I already have ${currentSticks.count} sticks. No crafting needed.`);
    return;
  }

  const plankNames = ["oak_planks", "spruce_planks", "birch_planks", "jungle_planks", "acacia_planks", "dark_oak_planks", "mangrove_planks"];
  const logNames = ["oak_log", "spruce_log", "birch_log", "jungle_log", "acacia_log", "dark_oak_log", "mangrove_log"];
  let plankCount = 0;
  for (const name of plankNames) {
    const item = mcData.itemsByName[name];
    if (!item) continue;
    const invItem = bot.inventory.findInventoryItem(item.id);
    if (invItem) plankCount += invItem.count;
  }

  if (plankCount < 2) {
    let logName = null;
    for (const name of logNames) {
      const item = mcData.itemsByName[name];
      if (!item) continue;
      const invItem = bot.inventory.findInventoryItem(item.id);
      if (invItem) {
        logName = name;
        break;
      }
    }
    if (!logName) {
      bot.chat("Not enough wood to craft sticks.");
      return;
    }
    const plankName = logName.replace("_log", "_planks");
    bot.chat(`Crafting ${plankName} from ${logName} first...`);
    await craftInventoryItem(bot, plankName, 1);
  }

  bot.chat("Crafting 4 sticks from 2 wooden planks...");
  await craftInventoryItem(bot, "stick", 1);
  const result = bot.inventory.findInventoryItem(stickItem.id);
  bot.chat(`Done! I now have ${result ? result.count : 0} sticks.`);
}
""",
}


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
    parser.add_argument(
        "--mode",
        choices=("agent", "direct"),
        default="agent",
        help="Use the full action agent loop or replay learned skills directly",
    )
    parser.add_argument(
        "--done-file",
        help="Optional file written when the run exits",
    )
    parser.add_argument(
        "--fallback-to-agent",
        action="store_true",
        help="When direct replay fails a task, retry that task once through the action agent",
    )
    parser.add_argument(
        "--start-from-ready-file",
        help="Optional ready.json path whose position is used when --position is not set explicitly",
    )
    parser.add_argument(
        "--spawn-from-world",
        action="store_true",
        help="Do not teleport during reset; spawn at the server-selected world spawn instead",
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


def has_error_event(events) -> bool:
    return any(event_type == "onError" for event_type, _ in events)


def final_snapshot(events) -> dict:
    if not events:
        return {}
    return events[-1][1]


def inventory_count(snapshot: dict, item_name: str) -> int:
    inventory = snapshot.get("inventory", {})
    return inventory.get(item_name, 0)


def has_equipped_item(snapshot: dict, item_name: str) -> bool:
    equipment = snapshot.get("status", {}).get("equipment", [])
    return item_name in equipment


def total_inventory_count(snapshot: dict, item_names: list[str]) -> int:
    return sum(inventory_count(snapshot, item_name) for item_name in item_names)


def task_item_total(snapshot: dict, item_name: str) -> int:
    if item_name == "wood_log":
        return total_inventory_count(snapshot, WOOD_LOG_NAMES)
    return inventory_count(snapshot, item_name)


def nearby_blocks(snapshot: dict) -> set[str]:
    blocks = set()
    for field in ("voxels", "blockRecords"):
        values = snapshot.get(field, [])
        if isinstance(values, list):
            blocks.update(value for value in values if isinstance(value, str))
    return blocks


def has_nearby_tree(snapshot: dict) -> bool:
    blocks = nearby_blocks(snapshot)
    return any(block_name in blocks for block_name in WOOD_LOG_NAMES)


def screen_spawn_for_tree(voyager: Voyager, tasks: list[str], attempts: int = 6) -> tuple[bool, str]:
    return screen_spawn_for_tree_with_metrics(voyager, tasks, attempts=attempts)


def screen_spawn_for_tree_with_metrics(
    voyager: Voyager,
    tasks: list[str],
    attempts: int = 6,
    metrics: dict | None = None,
) -> tuple[bool, str]:
    if not tasks or tasks[0] != "Mine 1 wood log":
        if metrics is not None:
            metrics["spawn_screening_required"] = False
            metrics["spawn_screening_attempts"] = 0
            metrics["spawn_screening_success"] = True
        return True, ""
    initial_has_tree = has_nearby_tree(final_snapshot(voyager.last_events))
    if metrics is not None:
        metrics["spawn_screening_required"] = True
        metrics["spawn_screening_attempts"] = 0
        metrics["spawn_screening_nearby_tree_initial"] = initial_has_tree
    if initial_has_tree:
        if metrics is not None:
            metrics["spawn_screening_success"] = True
        return True, ""
    for attempt in range(1, attempts + 1):
        print(f"Spawn screening attempt {attempt}/{attempts}: spreading to look for nearby trees")
        if metrics is not None:
            metrics["spawn_screening_attempts"] = attempt
        events = voyager.env.step(
            """
bot.chat('/spreadplayers ~ ~ 0 500 under 100 false @s');
await bot.waitForTicks(bot.waitTicks * 6);
""",
            programs=voyager.skill_manager.programs,
        )
        voyager.last_events = events
        if has_nearby_tree(final_snapshot(events)):
            if metrics is not None:
                metrics["spawn_screening_success"] = True
            return True, ""
    if metrics is not None:
        metrics["spawn_screening_success"] = False
    return False, "spawn screening could not place the bot near a visible tree/log block"


def has_nearby_or_inventory_crafting_table(snapshot: dict) -> bool:
    return inventory_count(snapshot, "crafting_table") > 0 or "crafting_table" in nearby_blocks(snapshot)


def load_position_from_ready_file(path: str | None) -> dict[str, float] | None:
    if not path:
        return None
    ready_payload = json.loads(Path(path).read_text(encoding="utf-8"))
    position = ready_payload.get("position")
    if not isinstance(position, dict):
        return None
    return {
        "x": float(position["x"]),
        "y": float(position["y"]),
        "z": float(position["z"]),
    }


def write_done_state(
    done_file: str | None,
    completed: list[str],
    failed: list[str],
    *,
    interrupted: bool = False,
    error: str | None = None,
    metrics: dict | None = None,
) -> None:
    if not done_file:
        return
    done_path = Path(done_file)
    done_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "completed": list(completed),
        "failed": list(failed),
    }
    if failed:
        payload["failed_task"] = failed[0]
    failure_reason = error
    if failure_reason is None and metrics:
        for outcome in reversed(metrics.get("task_outcomes", [])):
            if outcome.get("success"):
                continue
            if not failed or outcome.get("task") == failed[0]:
                failure_reason = outcome.get("error")
                break
    if interrupted:
        payload["interrupted"] = True
    if error:
        payload["error"] = error
    if failure_reason:
        payload["failure_reason"] = failure_reason
    if metrics:
        payload.update(metrics)
    done_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def note_fallback(metrics: dict | None, task: str, *, stage: str, reason: str) -> None:
    if metrics is None:
        return
    used_fallback_on_tasks = metrics.setdefault("used_fallback_on_tasks", [])
    if task not in used_fallback_on_tasks:
        used_fallback_on_tasks.append(task)
    metrics.setdefault("fallback_events", []).append(
        {
            "task": task,
            "stage": stage,
            "reason": reason,
        }
    )


def direct_precheck_failure(task: str, snapshot: dict) -> str | None:
    total_logs = total_inventory_count(snapshot, WOOD_LOG_NAMES)
    total_planks = total_inventory_count(snapshot, WOOD_PLANK_NAMES)
    stick_count = inventory_count(snapshot, "stick")
    cobblestone_count = inventory_count(snapshot, "cobblestone")
    has_table = has_nearby_or_inventory_crafting_table(snapshot)

    if task == "Craft 1 crafting_table":
        if inventory_count(snapshot, "crafting_table") > 0 or total_planks >= 4 or total_logs >= 1:
            return None
        return "need at least 4 planks or 1 log before direct crafting_table replay"

    if task == "Craft 4 sticks":
        if stick_count >= 4 or total_planks >= 2 or total_logs >= 1:
            return None
        return "need at least 2 planks or 1 log before direct stick crafting"

    if task == "Craft 1 wooden_pickaxe":
        if not has_table:
            return "need a nearby or inventory crafting_table before direct wooden_pickaxe replay"
        required_planks = 3 + (0 if stick_count >= 2 else 2)
        if total_planks + total_logs * 4 >= required_planks:
            return None
        return f"need at least {required_planks} planks worth of wood before direct wooden_pickaxe replay"

    if task == "Craft 1 stone_pickaxe":
        if not has_table:
            return "need a nearby or inventory crafting_table before direct stone_pickaxe replay"
        if cobblestone_count < 3:
            return "need at least 3 cobblestone before direct stone_pickaxe replay"
        if stick_count >= 2 or total_planks >= 2 or total_logs >= 1:
            return None
        return "need 2 sticks or enough wood to craft them before direct stone_pickaxe replay"

    if task == "Craft 1 furnace":
        if not has_table:
            return "need a nearby or inventory crafting_table before direct furnace replay"
        if cobblestone_count >= 8:
            return None
        return "need at least 8 cobblestone before direct furnace replay"

    return None


def validate_random_world_spawn(events, tasks: list[str]) -> tuple[bool, str]:
    snapshot = final_snapshot(events)
    if not tasks:
        return True, ""
    first_task = tasks[0]
    if first_task == "Mine 1 wood log" and not has_nearby_tree(snapshot):
        return False, "spawn area does not expose a nearby tree/log block"
    return True, ""


def run_agent_task(voyager: Voyager, task: str) -> dict:
    try:
        context = voyager.curriculum_agent.get_task_context(task)
        _, _, _, info = voyager.rollout(
            task=task,
            context=context,
            reset_env=False,
        )
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        info = {
            "task": task,
            "success": False,
            "error": str(exc),
        }
    info["task"] = info.get("task", task)
    info["success"] = bool(info.get("success"))
    return info


def record_task_outcome(
    voyager: Voyager,
    info: dict,
    completed: list[str],
    failed: list[str],
    progress_callback: Callable[[], None] | None = None,
    metrics: dict | None = None,
) -> None:
    voyager.curriculum_agent.update_exploration_progress(info)
    if info["success"]:
        completed.append(info["task"])
    else:
        failed.append(info["task"])
    if metrics is not None:
        metrics.setdefault("task_outcomes", []).append(
            {
                "task": info.get("task"),
                "success": bool(info.get("success")),
                "error": str(info.get("error")) if info.get("error") is not None else None,
            }
        )
    if progress_callback is not None:
        progress_callback()


def validate_direct_task(task: str, before_snapshot: dict, events) -> tuple[bool, str]:
    snapshot = final_snapshot(events)
    match = re.match(r"^(Mine|Craft) (\d+) (.+)$", task)
    if match:
        action, amount_text, raw_item = match.groups()
        amount = int(amount_text)
        item_name = TASK_ITEM_ALIASES.get(raw_item, raw_item).replace(" ", "_")
        before_total = task_item_total(before_snapshot, item_name)
        after_total = task_item_total(snapshot, item_name)
        if action == "Mine":
            if after_total >= before_total + amount:
                return True, ""
            if before_total < amount and after_total >= amount:
                return True, ""
            return False, (
                f"expected to mine {amount} {item_name}, inventory moved from {before_total} to {after_total}"
            )
        if item_name == "stick":
            if after_total >= before_total + amount:
                return True, ""
        if after_total >= amount:
            return True, ""
        if has_equipped_item(snapshot, item_name):
            return True, ""
        return False, f"expected at least {amount} {item_name}, found {after_total}"

    match = re.match(r"^Equip (.+)$", task)
    if match:
        item_name = match.group(1).replace(" ", "_")
        if has_equipped_item(snapshot, item_name):
            return True, ""
        return False, f"expected {item_name} to be equipped"

    return False, f"no direct validator for task: {task}"


def run_direct_sequence(
    voyager: Voyager,
    tasks: list[str],
    completed: list[str],
    failed: list[str],
    fallback_to_agent: bool = False,
    progress_callback: Callable[[], None] | None = None,
    metrics: dict | None = None,
) -> None:
    for task in tasks:
        before_snapshot = final_snapshot(voyager.last_events)
        precheck_failure = direct_precheck_failure(task, before_snapshot)
        if precheck_failure:
            if fallback_to_agent:
                print(f"Direct precheck failed, retrying with agent: {task}: {precheck_failure}")
                note_fallback(metrics, task, stage="precheck", reason=precheck_failure)
                info = run_agent_task(voyager, task)
                record_task_outcome(voyager, info, completed, failed, progress_callback, metrics)
                if info["success"]:
                    continue
                print(f"Agent fallback failed for {task}: {info.get('error')}")
                break
            record_task_outcome(
                voyager,
                {"task": task, "success": False, "error": precheck_failure},
                completed,
                failed,
                progress_callback,
                metrics,
            )
            print(f"Direct precheck failed for {task}: {precheck_failure}")
            break
        skill_name = TASK_TO_SKILL.get(task)
        if not skill_name:
            if fallback_to_agent:
                print(f"No direct skill mapping for task, retrying with agent: {task}")
                note_fallback(metrics, task, stage="mapping", reason="no direct skill mapping")
                info = run_agent_task(voyager, task)
                record_task_outcome(voyager, info, completed, failed, progress_callback, metrics)
                if info["success"]:
                    continue
                print(f"Agent fallback failed for {task}: {info.get('error')}")
                break
            record_task_outcome(
                voyager,
                {"task": task, "success": False, "error": "no direct skill mapping"},
                completed,
                failed,
                progress_callback,
                metrics,
            )
            print(f"No direct skill mapping for task: {task}")
            break
        print(f"Running learned skill {skill_name} for task: {task}")
        programs = voyager.skill_manager.programs
        if skill_name in DIRECT_SKILL_OVERRIDES:
            programs = programs + "\n\n" + DIRECT_SKILL_OVERRIDES[skill_name]
        try:
            events = voyager.env.step(
                f"await {skill_name}(bot)",
                programs=programs,
            )
        except Exception as exc:
            if fallback_to_agent:
                print(f"Direct skill run failed, retrying with agent: {task}: {exc}")
                note_fallback(metrics, task, stage="direct_exception", reason=str(exc))
                info = run_agent_task(voyager, task)
                record_task_outcome(voyager, info, completed, failed, progress_callback, metrics)
                if info["success"]:
                    continue
                print(f"Agent fallback failed for {task}: {info.get('error')}")
                break
            print(f"Direct skill run failed for {task}: {exc}")
            record_task_outcome(
                voyager,
                {"task": task, "success": False, "error": str(exc)},
                completed,
                failed,
                progress_callback,
                metrics,
            )
            break
        voyager.recorder.record(events, task)
        voyager.last_events = events
        if has_error_event(events):
            if fallback_to_agent:
                print(f"Task produced onError events in direct mode, retrying with agent: {task}")
                note_fallback(metrics, task, stage="onError", reason="onError event")
                info = run_agent_task(voyager, task)
                record_task_outcome(voyager, info, completed, failed, progress_callback, metrics)
                if info["success"]:
                    continue
                print(f"Agent fallback failed for {task}: {info.get('error')}")
                break
            record_task_outcome(
                voyager,
                {"task": task, "success": False, "error": "onError event"},
                completed,
                failed,
                progress_callback,
                metrics,
            )
            print(f"Task produced onError events: {task}")
            break
        valid, reason = validate_direct_task(task, before_snapshot, events)
        if not valid:
            if fallback_to_agent:
                print(f"Task validation failed in direct mode, retrying with agent: {task}: {reason}")
                note_fallback(metrics, task, stage="validation", reason=reason)
                info = run_agent_task(voyager, task)
                record_task_outcome(voyager, info, completed, failed, progress_callback, metrics)
                if info["success"]:
                    continue
                print(f"Agent fallback failed for {task}: {info.get('error')}")
                break
            record_task_outcome(
                voyager,
                {"task": task, "success": False, "error": reason},
                completed,
                failed,
                progress_callback,
                metrics,
            )
            print(f"Task validation failed for {task}: {reason}")
            break
        record_task_outcome(
            voyager,
            {"task": task, "success": True},
            completed,
            failed,
            progress_callback,
            metrics,
        )


def main() -> None:
    args = build_parser().parse_args()
    model_name = os.environ.get("VOYAGER_MODEL_NAME", "kimi-k2.6")
    started_at = time.monotonic()
    completed: list[str] = []
    failed: list[str] = []
    interrupted = False
    terminal_error: str | None = None
    run_metrics: dict = {
        "mode": args.mode,
        "used_fallback_on_tasks": [],
        "fallback_events": [],
        "task_outcomes": [],
    }
    ready_position = load_position_from_ready_file(args.start_from_ready_file)
    if args.start_from_ready_file and ready_position is None:
        args.spawn_from_world = True
    if ready_position is not None and args.position == DEFAULT_POSITION and not args.spawn_from_world:
        args.position = ready_position

    def persist_done_state() -> None:
        run_metrics["duration_seconds"] = round(time.monotonic() - started_at, 2)
        run_metrics["fallback_count"] = len(run_metrics.get("fallback_events", []))
        write_done_state(
            args.done_file,
            completed,
            failed,
            interrupted=interrupted,
            error=terminal_error,
            metrics=run_metrics,
        )

    print("=" * 60)
    print("VOYAGER RECORDED DEMO")
    print("=" * 60)
    print(f"Minecraft port: {args.port}")
    print(f"Checkpoint dir: {args.ckpt_dir}")
    print(f"Skill library: {args.skill_library_dir}")
    print(f"Mode: {args.mode}")
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
        }
        if not args.spawn_from_world:
            reset_options["position"] = args.position
        if args.reset_mode == "hard" and args.inventory:
            reset_options["inventory"] = args.inventory
        voyager.last_events = voyager.env.reset(
            options=reset_options
        )
        if args.spawn_from_world:
            spawn_ok, spawn_reason = screen_spawn_for_tree_with_metrics(voyager, args.tasks, metrics=run_metrics)
        else:
            spawn_ok, spawn_reason = validate_random_world_spawn(voyager.last_events, args.tasks)
            run_metrics["spawn_screening_required"] = False
            run_metrics["spawn_screening_attempts"] = 0
            run_metrics["spawn_screening_success"] = bool(spawn_ok)
            if args.tasks and args.tasks[0] == "Mine 1 wood log":
                run_metrics["spawn_screening_nearby_tree_initial"] = has_nearby_tree(final_snapshot(voyager.last_events))
        if not spawn_ok:
            failed = [args.tasks[0]] if args.tasks else []
            terminal_error = spawn_reason
            persist_done_state()
            print(f"Spawn validation failed: {spawn_reason}")
            print("\n" + "=" * 60)
            print("RECORDED DEMO COMPLETE")
            print("=" * 60)
            print(f"Completed tasks: {completed}")
            print(f"Failed tasks: {failed}")
            return

        if args.mode == "direct":
            run_direct_sequence(
                voyager,
                args.tasks,
                completed,
                failed,
                fallback_to_agent=args.fallback_to_agent,
                metrics=run_metrics,
            )
        else:
            for task in args.tasks:
                info = run_agent_task(voyager, task)
                record_task_outcome(voyager, info, completed, failed, metrics=run_metrics)
                if not info["success"]:
                    break

        print("\n" + "=" * 60)
        print("RECORDED DEMO COMPLETE")
        print("=" * 60)
        print(f"Completed tasks: {completed}")
        print(f"Failed tasks: {failed}")
    except KeyboardInterrupt:
        interrupted = True
        if not failed and len(completed) < len(args.tasks):
            failed.append(args.tasks[len(completed)])
        terminal_error = "interrupted"
        persist_done_state()
        print("\nInterrupted by user.")
    except Exception as exc:
        terminal_error = str(exc)
        if not failed and len(completed) < len(args.tasks):
            failed.append(args.tasks[len(completed)])
        persist_done_state()
        raise
    finally:
        try:
            voyager.close()
        finally:
            persist_done_state()
        print("Voyager closed.")


if __name__ == "__main__":
    main()
