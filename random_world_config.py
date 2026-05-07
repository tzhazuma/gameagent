"""Shared random-world preset metadata and naming helpers."""

from __future__ import annotations

import re
from pathlib import Path


RANDOM_WORLD_TASK_PRESETS = {
    "short-random": (
        "Mine 1 wood log",
        "Craft 1 crafting_table",
    ),
    "long-random": (
        "Mine 1 wood log",
        "Craft 1 crafting_table",
        "Mine 1 wood log",
        "Craft 4 sticks",
    ),
    "woodpick-random": (
        "Mine 1 wood log",
        "Craft 1 crafting_table",
        "Mine 1 wood log",
        "Craft 4 sticks",
        "Mine 1 wood log",
        "Craft 1 wooden_pickaxe",
    ),
}

RANDOM_WORLD_TASK_PRESET_NAMES = tuple(RANDOM_WORLD_TASK_PRESETS)

RANDOM_WORLD_LABEL_PREFIXES = {
    "short-random": "random-world",
    "long-random": "random-world-long",
    "woodpick-random": "random-world-woodpick",
}


def get_random_world_tasks(task_preset: str) -> list[str]:
    return list(RANDOM_WORLD_TASK_PRESETS[task_preset])


def is_random_world_task_preset(task_preset: str | None) -> bool:
    return task_preset in RANDOM_WORLD_TASK_PRESETS


def default_label_prefix(task_preset: str) -> str:
    return RANDOM_WORLD_LABEL_PREFIXES[task_preset]


def slugify_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "run"


def resolve_relative_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def path_for_display(root: Path, value: Path) -> str:
    try:
        return str(value.relative_to(root))
    except ValueError:
        return str(value)


def default_validation_ckpt_dir(label: str) -> str:
    return f"ckpt_{slugify_name(label)}"


def default_validation_server_root(label: str) -> str:
    return f".demo_server_{slugify_name(label)}"


def default_benchmark_output(task_preset: str, *, label_prefix: str | None = None) -> str:
    prefix = label_prefix or default_label_prefix(task_preset)
    return f"recordings/{prefix}-benchmark.json"


def default_benchmark_artifacts_dir(task_preset: str, *, label_prefix: str | None = None) -> str:
    prefix = label_prefix or default_label_prefix(task_preset)
    return f"recordings/_runs/{prefix}"
