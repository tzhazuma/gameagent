#!/usr/bin/env python3
"""Generate visual demos from ckpt_voyager event logs."""

from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CKPT_DIR = ROOT / "ckpt_voyager"
EVENTS_DIR = CKPT_DIR / "events"
OUTPUT_DIRS = [ROOT / "demo", ROOT / "docs"]

TIMESTAMP_RE = re.compile(r"_(\d{8})_(\d{6})$")
TASK_COLORS = {
    "Mine": "#60a5fa",
    "Craft": "#f59e0b",
    "Smelt": "#f97316",
    "Equip": "#10b981",
    "Kill": "#ef4444",
    "Other": "#a78bfa",
}
STATUS_COLORS = {
    "completed": "#22c55e",
    "failed": "#ef4444",
    "missing": "#94a3b8",
}
BIOME_COLORS = {
    "snowy_plains": "#93c5fd",
    "snowy_taiga": "#34d399",
    "frozen_ocean": "#67e8f9",
    "windswept_forest": "#fca5a5",
}


@dataclass
class Episode:
    filename: str
    task_key: str
    timestamp: datetime
    duration_ticks: int
    final_status: dict
    final_inventory: dict
    chat_messages: list[str]

    @property
    def x(self) -> float:
        return float(self.final_status["position"]["x"])

    @property
    def z(self) -> float:
        return float(self.final_status["position"]["z"])

    @property
    def biome(self) -> str:
        return self.final_status.get("biome", "unknown")

    @property
    def time_of_day(self) -> str:
        return self.final_status.get("timeOfDay", "unknown")

    @property
    def inventory_items(self) -> list[tuple[str, int]]:
        return sorted(self.final_inventory.items(), key=lambda item: (-item[1], item[0]))

    @property
    def equipment(self) -> list[str | None]:
        return self.final_status.get("equipment", [])


def canonical_task(task_name: str) -> str:
    return task_name.replace(" ", "_")


def parse_episode(file_path: Path) -> Episode:
    match = TIMESTAMP_RE.search(file_path.name)
    if not match:
        raise ValueError(f"Unsupported event filename: {file_path.name}")
    timestamp = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    task_key = file_path.name[: match.start()]
    with open(file_path, "r", encoding="utf-8") as handle:
        events = json.load(handle)

    payloads = [payload for _, payload in events if "status" in payload]
    if not payloads:
        raise ValueError(f"Event file has no status payloads: {file_path.name}")

    final_payload = payloads[-1]
    final_status = final_payload["status"]
    duration_ticks = int(final_status.get("elapsedTime", 0))
    chat_messages = [payload["onChat"] for event_type, payload in events if event_type == "onChat"]
    return Episode(
        filename=file_path.name,
        task_key=task_key,
        timestamp=timestamp,
        duration_ticks=duration_ticks,
        final_status=final_status,
        final_inventory=final_payload.get("inventory", {}),
        chat_messages=chat_messages,
    )


def load_episodes() -> list[Episode]:
    episodes = [parse_episode(path) for path in EVENTS_DIR.iterdir() if path.is_file()]
    return sorted(episodes, key=lambda episode: episode.timestamp)


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def task_category(task_name: str) -> str:
    prefix = task_name.split(" ", 1)[0]
    return prefix if prefix in TASK_COLORS else "Other"


def color_for_biome(biome: str) -> str:
    return BIOME_COLORS.get(biome, "#cbd5e1")


def human_ticks(ticks: int) -> str:
    seconds = ticks / 20
    minutes, seconds = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{ticks}t / {hours}h {minutes:02d}m"
    return f"{ticks}t / {minutes}m {seconds:02d}s"


def clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def episode_lookup_for_completed_tasks(
    completed_tasks: list[str], episodes: list[Episode]
) -> dict[str, Episode]:
    selected: dict[str, Episode] = {}
    start_index = 0
    for task_index, task_name in enumerate(completed_tasks):
        key = canonical_task(task_name)
        next_key = (
            canonical_task(completed_tasks[task_index + 1])
            if task_index + 1 < len(completed_tasks)
            else None
        )
        end_index = len(episodes)
        if next_key:
            for idx in range(start_index, len(episodes)):
                if episodes[idx].task_key == next_key:
                    end_index = idx
                    break
        matches = [episode for episode in episodes[start_index:end_index] if episode.task_key == key]
        if matches:
            selected[task_name] = matches[-1]
            start_index = episodes.index(matches[-1]) + 1
    return selected


def episode_lookup_for_failed_tasks(
    failed_tasks: list[str], episodes: list[Episode]
) -> dict[str, Episode]:
    selected: dict[str, Episode] = {}
    for task_name in failed_tasks:
        key = canonical_task(task_name)
        matches = [episode for episode in episodes if episode.task_key == key]
        if matches:
            selected[task_name] = matches[-1]
    return selected


def build_official_task_rows(
    completed_tasks: list[str],
    failed_tasks: list[str],
    completed_lookup: dict[str, Episode],
    failed_lookup: dict[str, Episode],
) -> list[dict]:
    rows = []
    order = completed_tasks + [task for task in failed_tasks if task not in completed_tasks]
    for index, task_name in enumerate(order, start=1):
        episode = completed_lookup.get(task_name) or failed_lookup.get(task_name)
        status = "completed" if task_name in completed_lookup else "failed"
        if task_name in failed_tasks and task_name not in completed_lookup:
            status = "failed"
        if episode is None:
            rows.append(
                {
                    "index": index,
                    "name": task_name,
                    "category": task_category(task_name),
                    "status": "missing",
                    "duration_ticks": 0,
                    "duration_label": "no saved event",
                    "biome": "n/a",
                    "time_of_day": "n/a",
                    "position": None,
                    "health": None,
                    "food": None,
                    "equipment": [],
                    "inventory": [],
                    "chat_messages": [],
                    "timestamp": None,
                    "source_file": None,
                }
            )
            continue

        rows.append(
            {
                "index": index,
                "name": task_name,
                "category": task_category(task_name),
                "status": status,
                "duration_ticks": episode.duration_ticks,
                "duration_label": human_ticks(episode.duration_ticks),
                "biome": episode.biome,
                "time_of_day": episode.time_of_day,
                "position": {"x": episode.x, "z": episode.z},
                "health": episode.final_status.get("health"),
                "food": episode.final_status.get("food"),
                "equipment": episode.equipment,
                "inventory": episode.inventory_items,
                "chat_messages": episode.chat_messages,
                "timestamp": episode.timestamp.isoformat(),
                "source_file": episode.filename,
            }
        )
    return rows


def build_item_milestones(episodes: list[Episode]) -> list[dict]:
    milestones = []
    seen_items: set[str] = set()
    cumulative_ticks = 0
    for episode in episodes:
        cumulative_ticks += episode.duration_ticks
        inventory_items = set(episode.final_inventory)
        new_items = sorted(inventory_items - seen_items)
        for item_name in new_items:
            milestones.append(
                {
                    "item": item_name,
                    "task_key": episode.task_key,
                    "ticks": cumulative_ticks,
                    "label": human_ticks(cumulative_ticks),
                    "source_file": episode.filename,
                }
            )
        seen_items.update(inventory_items)
    return milestones


def build_summary_data() -> dict:
    episodes = load_episodes()
    completed_tasks = load_json(CKPT_DIR / "curriculum" / "completed_tasks.json")
    failed_tasks = load_json(CKPT_DIR / "curriculum" / "failed_tasks.json")
    skills = load_json(CKPT_DIR / "skill" / "skills.json")

    completed_lookup = episode_lookup_for_completed_tasks(completed_tasks, episodes)
    failed_lookup = episode_lookup_for_failed_tasks(failed_tasks, episodes)
    official_tasks = build_official_task_rows(
        completed_tasks, failed_tasks, completed_lookup, failed_lookup
    )

    selected_route = [
        row
        for row in official_tasks
        if row["position"] is not None
    ]

    latest_episode = episodes[-1]
    final_inventory = sorted(
        latest_episode.final_inventory.items(), key=lambda item: (-item[1], item[0])
    )
    biomes = sorted({episode.biome for episode in episodes})
    total_ticks = sum(episode.duration_ticks for episode in episodes)
    official_keys = {canonical_task(task) for task in completed_tasks + failed_tasks}
    unique_episode_keys = {episode.task_key for episode in episodes}
    off_path_keys = sorted(unique_episode_keys - official_keys)
    all_episodes = [
        {
            "task_key": episode.task_key,
            "timestamp": episode.timestamp.isoformat(),
            "duration_ticks": episode.duration_ticks,
            "duration_label": human_ticks(episode.duration_ticks),
            "biome": episode.biome,
            "time_of_day": episode.time_of_day,
            "position": {"x": episode.x, "z": episode.z},
            "health": episode.final_status.get("health"),
            "food": episode.final_status.get("food"),
            "equipment": episode.equipment,
            "inventory": episode.inventory_items,
            "chat_messages": episode.chat_messages,
            "source_file": episode.filename,
            "official_task": episode.task_key in official_keys,
        }
        for episode in episodes
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "completed_tasks": len(completed_tasks),
            "failed_tasks": len(failed_tasks),
            "official_tasks": len(completed_tasks) + len(failed_tasks),
            "skills": len(skills),
            "recorded_episodes": len(episodes),
            "recorded_ticks": total_ticks,
            "recorded_ticks_label": human_ticks(total_ticks),
            "biomes": biomes,
            "official_snapshots": len(selected_route),
            "off_path_unique_tasks": off_path_keys,
        },
        "official_tasks": official_tasks,
        "episodes": all_episodes,
        "route": selected_route,
        "latest_snapshot": {
            "biome": latest_episode.biome,
            "time_of_day": latest_episode.time_of_day,
            "position": {"x": latest_episode.x, "z": latest_episode.z},
            "health": latest_episode.final_status.get("health"),
            "food": latest_episode.final_status.get("food"),
            "equipment": latest_episode.final_status.get("equipment", []),
            "inventory": final_inventory,
            "source_file": latest_episode.filename,
        },
        "item_milestones": build_item_milestones(episodes),
    }


def svg_text(x: float, y: float, text: str, size: int = 24, fill: str = "#e5e7eb", weight: int = 400) -> str:
    safe = html.escape(text)
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" '
        f'font-family="Inter,Segoe UI,Arial,sans-serif" font-weight="{weight}">{safe}</text>'
    )


def svg_rect(x: float, y: float, width: float, height: float, fill: str, radius: int = 18, stroke: str | None = None, stroke_width: int = 1) -> str:
    stroke_attr = ""
    if stroke:
        stroke_attr = f' stroke="{stroke}" stroke-width="{stroke_width}"'
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
        f'fill="{fill}"{stroke_attr}/>'
    )


def render_dashboard_svg(data: dict) -> str:
    width = 1440
    height = 980
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#0f172a"/><stop offset="100%" stop-color="#111827"/></linearGradient></defs>',
        '<rect width="100%" height="100%" fill="url(#bg)"/>',
    ]

    parts.append(svg_text(48, 64, "Voyager LAN Run Demo", 34, "#f8fafc", 700))
    parts.append(svg_text(48, 98, "Generated from the real ckpt_voyager checkpoint", 17, "#94a3b8"))

    metrics = [
        ("Completed", str(data["summary"]["completed_tasks"]), "#22c55e"),
        ("Failed", str(data["summary"]["failed_tasks"]), "#ef4444"),
        ("Skills", str(data["summary"]["skills"]), "#a78bfa"),
        ("Episodes", str(data["summary"]["recorded_episodes"]), "#38bdf8"),
        ("Recorded Time", data["summary"]["recorded_ticks_label"], "#f59e0b"),
    ]
    metric_x = 48
    for label, value, accent in metrics:
        parts.append(svg_rect(metric_x, 130, 250, 104, "#111827", 20, "#1f2937"))
        parts.append(svg_rect(metric_x + 18, 148, 8, 68, accent, 4))
        parts.append(svg_text(metric_x + 42, 168, label, 16, "#94a3b8", 500))
        parts.append(svg_text(metric_x + 42, 205, value, 28, "#f8fafc", 700))
        metric_x += 270

    map_x = 48
    map_y = 270
    map_w = 760
    map_h = 420
    parts.append(svg_rect(map_x, map_y, map_w, map_h, "#0b1220", 24, "#1f2937"))
    parts.append(svg_text(map_x + 24, map_y + 38, "Curriculum Route", 22, "#f8fafc", 650))
    parts.append(svg_text(map_x + 24, map_y + 62, "Selected task snapshots across the real world run", 14, "#94a3b8"))

    route = data["route"]
    if route:
        xs = [point["position"]["x"] for point in route]
        zs = [point["position"]["z"] for point in route]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        if math.isclose(min_x, max_x):
            max_x += 1
        if math.isclose(min_z, max_z):
            max_z += 1
        inner_left = map_x + 36
        inner_top = map_y + 88
        inner_w = map_w - 72
        inner_h = map_h - 130

        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            grid_x = inner_left + inner_w * fraction
            grid_y = inner_top + inner_h * fraction
            parts.append(f'<line x1="{grid_x}" y1="{inner_top}" x2="{grid_x}" y2="{inner_top + inner_h}" stroke="#1f2937" stroke-width="1"/>')
            parts.append(f'<line x1="{inner_left}" y1="{grid_y}" x2="{inner_left + inner_w}" y2="{grid_y}" stroke="#1f2937" stroke-width="1"/>')

        def scale_point(raw_x: float, raw_z: float) -> tuple[float, float]:
            px = inner_left + (raw_x - min_x) / (max_x - min_x) * inner_w
            py = inner_top + inner_h - (raw_z - min_z) / (max_z - min_z) * inner_h
            return px, py

        poly_points = [scale_point(point["position"]["x"], point["position"]["z"]) for point in route]
        point_string = " ".join(f"{x:.1f},{y:.1f}" for x, y in poly_points)
        parts.append(f'<polyline points="{point_string}" fill="none" stroke="#60a5fa" stroke-width="4" stroke-linejoin="round" stroke-linecap="round" opacity="0.8"/>')

        for point, (px, py) in zip(route, poly_points):
            fill = STATUS_COLORS.get(point["status"], "#cbd5e1")
            category_fill = TASK_COLORS.get(point["category"], TASK_COLORS["Other"])
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="7" fill="{fill}" stroke="{category_fill}" stroke-width="3"/>')

        start_x, start_y = poly_points[0]
        end_x, end_y = poly_points[-1]
        parts.append(f'<circle cx="{start_x:.1f}" cy="{start_y:.1f}" r="10" fill="#22c55e" stroke="#ecfeff" stroke-width="2"/>')
        parts.append(f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="10" fill="#f59e0b" stroke="#ecfeff" stroke-width="2"/>')
        parts.append(svg_text(start_x + 14, start_y - 10, "Start", 14, "#d1fae5", 600))
        parts.append(svg_text(end_x + 14, end_y - 10, "Latest", 14, "#fde68a", 600))
        parts.append(svg_text(inner_left, map_y + map_h - 26, f"X range: {min_x:.1f} to {max_x:.1f}", 13, "#64748b"))
        parts.append(svg_text(inner_left + 250, map_y + map_h - 26, f"Z range: {min_z:.1f} to {max_z:.1f}", 13, "#64748b"))

    side_x = 840
    side_y = 270
    side_w = 552
    parts.append(svg_rect(side_x, side_y, side_w, 210, "#0b1220", 24, "#1f2937"))
    parts.append(svg_text(side_x + 24, side_y + 38, "Latest Snapshot", 22, "#f8fafc", 650))
    latest = data["latest_snapshot"]
    parts.append(svg_text(side_x + 24, side_y + 72, f"Biome: {latest['biome']}", 16))
    parts.append(svg_text(side_x + 24, side_y + 100, f"Time: {latest['time_of_day']}", 16))
    parts.append(svg_text(side_x + 24, side_y + 128, f"Position: x={latest['position']['x']:.1f}, z={latest['position']['z']:.1f}", 16))
    parts.append(svg_text(side_x + 24, side_y + 156, f"Health/Food: {latest['health']} / {latest['food']}", 16))
    equipped = [item for item in latest["equipment"] if item]
    equipment_label = ", ".join(equipped) if equipped else "none"
    parts.append(svg_text(side_x + 24, side_y + 184, f"Equipment: {equipment_label}", 16))

    parts.append(svg_rect(side_x, side_y + 230, side_w, 190, "#0b1220", 24, "#1f2937"))
    parts.append(svg_text(side_x + 24, side_y + 268, "Biomes Visited", 22, "#f8fafc", 650))
    chip_x = side_x + 24
    chip_y = side_y + 304
    for biome in data["summary"]["biomes"]:
        label = biome
        chip_w = 20 + len(label) * 8
        if chip_x + chip_w > side_x + side_w - 24:
            chip_x = side_x + 24
            chip_y += 42
        parts.append(svg_rect(chip_x, chip_y, chip_w, 30, color_for_biome(biome), 15))
        parts.append(svg_text(chip_x + 12, chip_y + 21, label, 13, "#0f172a", 700))
        chip_x += chip_w + 10
    off_path = data["summary"]["off_path_unique_tasks"]
    parts.append(svg_text(side_x + 24, side_y + 392, f"Off-path recorded tasks: {', '.join(off_path) if off_path else 'none'}", 14, "#94a3b8"))

    bottom_y = 720
    left_bottom_w = 680
    parts.append(svg_rect(48, bottom_y, left_bottom_w, 220, "#0b1220", 24, "#1f2937"))
    parts.append(svg_text(72, bottom_y + 38, "Inventory Milestones", 22, "#f8fafc", 650))
    milestone_y = bottom_y + 72
    for milestone in data["item_milestones"][:10]:
        parts.append(svg_text(72, milestone_y, f"{milestone['item']}  ({milestone['label']})", 16))
        parts.append(svg_text(340, milestone_y, milestone["task_key"], 15, "#94a3b8"))
        milestone_y += 28

    right_bottom_x = 760
    right_bottom_w = 632
    parts.append(svg_rect(right_bottom_x, bottom_y, right_bottom_w, 220, "#0b1220", 24, "#1f2937"))
    parts.append(svg_text(right_bottom_x + 24, bottom_y + 38, "Top Inventory In Latest Snapshot", 22, "#f8fafc", 650))
    inventory_y = bottom_y + 72
    for item_name, count in data["latest_snapshot"]["inventory"][:10]:
        bar_width = clip(count * 6, 24, 240)
        parts.append(svg_text(right_bottom_x + 24, inventory_y, item_name, 15))
        parts.append(svg_rect(right_bottom_x + 220, inventory_y - 16, bar_width, 16, "#334155", 8))
        parts.append(svg_rect(right_bottom_x + 220, inventory_y - 16, clip(count * 4, 18, 180), 16, "#38bdf8", 8))
        parts.append(svg_text(right_bottom_x + 220 + bar_width + 12, inventory_y - 2, str(count), 14, "#e2e8f0", 600))
        inventory_y += 22

    legend_x = map_x + 24
    legend_y = map_y + map_h - 58
    legend = [("completed", "Completed"), ("failed", "Failed"), ("missing", "Missing")]
    for key, label in legend:
        parts.append(f'<circle cx="{legend_x}" cy="{legend_y}" r="6" fill="{STATUS_COLORS[key]}"/>')
        parts.append(svg_text(legend_x + 14, legend_y + 5, label, 13, "#cbd5e1"))
        legend_x += 110

    parts.append('</svg>')
    return "".join(parts)


def render_tasks_svg(data: dict) -> str:
    rows = data["official_tasks"]
    width = 1440
    row_height = 34
    height = 150 + len(rows) * row_height
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0f172a"/>',
        svg_text(40, 54, "Official Task Timeline", 32, "#f8fafc", 700),
        svg_text(40, 84, "Bar length is the saved task duration; colors show task type and outcome.", 16, "#94a3b8"),
    ]

    max_ticks = max((row["duration_ticks"] for row in rows), default=1)
    bar_start = 620
    bar_width = 460
    y = 120
    for row in rows:
        parts.append(svg_rect(24, y - 22, width - 48, 28, "#111827", 12, "#1f2937"))
        parts.append(svg_text(42, y - 2, f"{row['index']:02d}", 14, "#94a3b8", 700))
        parts.append(svg_text(88, y - 2, row["name"], 15, "#f8fafc", 600))
        category_color = TASK_COLORS.get(row["category"], TASK_COLORS["Other"])
        parts.append(svg_rect(490, y - 18, 96, 18, category_color, 9))
        parts.append(svg_text(503, y - 4, row["category"], 12, "#0f172a", 700))

        parts.append(svg_rect(bar_start, y - 16, bar_width, 14, "#1f2937", 7))
        if row["duration_ticks"]:
            filled = max(10, row["duration_ticks"] / max_ticks * bar_width)
            parts.append(svg_rect(bar_start, y - 16, filled, 14, STATUS_COLORS[row["status"]], 7))
        status_x = 1100
        parts.append(svg_rect(status_x, y - 18, 96, 18, STATUS_COLORS[row["status"]], 9))
        parts.append(svg_text(status_x + 14, y - 4, row["status"], 12, "#0f172a", 700))
        parts.append(svg_text(1220, y - 2, row["duration_label"], 14, "#e2e8f0", 600))
        biome_label = row["biome"]
        parts.append(svg_text(1320, y - 2, biome_label, 13, color_for_biome(biome_label) if biome_label != "n/a" else "#94a3b8", 700))
        y += row_height

    parts.append('</svg>')
    return "".join(parts)


def render_html(data: dict) -> str:
    summary = data["summary"]
    json_payload = json.dumps(data).replace("</", "<\\/")
    milestone_rows = "".join(
        f'<tr><td>{html.escape(m["item"])}</td><td>{html.escape(m["task_key"])}</td><td>{html.escape(m["label"])}</td></tr>'
        for m in data["item_milestones"][:20]
    )
    inventory_rows = "".join(
        f'<tr><td>{html.escape(item)}</td><td>{count}</td></tr>'
        for item, count in data["latest_snapshot"]["inventory"][:20]
    )
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Voyager Checkpoint Explorer</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #020617;
      --panel: #0f172a;
      --muted: #94a3b8;
      --text: #e2e8f0;
      --border: #1e293b;
      --green: #22c55e;
      --red: #ef4444;
      --amber: #f59e0b;
      --blue: #38bdf8;
      --purple: #a78bfa;
      --shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font: 15px/1.5 Inter, Segoe UI, Arial, sans-serif; background: radial-gradient(circle at top, rgba(56, 189, 248, 0.16), transparent 32%), linear-gradient(180deg, #020617 0%, #0f172a 100%); color: var(--text); }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    main {{ max-width: 1480px; margin: 0 auto; padding: 32px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    p {{ margin: 0 0 16px; color: var(--muted); }}
    .hero {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin: 24px 0; }}
    .card {{ background: rgba(15, 23, 42, 0.9); border: 1px solid var(--border); border-radius: 18px; padding: 18px; box-shadow: var(--shadow); }}
    .metric {{ font-size: 28px; font-weight: 700; color: white; }}
    .images {{ display: grid; gap: 16px; }}
    img {{ width: 100%; border-radius: 18px; border: 1px solid var(--border); background: #0b1220; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; border-radius: 18px; border: 1px solid var(--border); background: rgba(15, 23, 42, 0.92); }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    th {{ color: white; background: rgba(30, 41, 59, 0.7); }}
    .status.completed {{ color: var(--green); font-weight: 700; }}
    .status.failed {{ color: var(--red); font-weight: 700; }}
    .status.missing {{ color: var(--muted); font-weight: 700; }}
    .notes {{ display: grid; gap: 16px; grid-template-columns: 1.2fr 1fr; margin-top: 16px; }}
    .toolbar {{ display: grid; gap: 12px; grid-template-columns: 1.4fr repeat(3, minmax(140px, 1fr)); margin-top: 18px; }}
    .toolbar label {{ display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; }}
    .toolbar input, .toolbar select {{ width: 100%; padding: 11px 12px; border-radius: 12px; border: 1px solid var(--border); background: rgba(2, 6, 23, 0.9); color: var(--text); }}
    .explorer {{ display: grid; gap: 16px; grid-template-columns: 1.1fr 0.9fr; margin-top: 16px; }}
    .panel {{ background: rgba(15, 23, 42, 0.92); border: 1px solid var(--border); border-radius: 20px; padding: 18px; box-shadow: var(--shadow); }}
    .route-map {{ width: 100%; aspect-ratio: 16 / 10; background: linear-gradient(180deg, rgba(2, 6, 23, 0.82), rgba(15, 23, 42, 0.65)); border: 1px solid var(--border); border-radius: 18px; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin-top: 14px; color: var(--muted); font-size: 13px; }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 8px; }}
    .legend-dot {{ width: 10px; height: 10px; border-radius: 999px; display: inline-block; }}
    .task-grid {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
    .task-card {{ text-align: left; border: 1px solid var(--border); background: rgba(2, 6, 23, 0.6); color: inherit; border-radius: 16px; padding: 14px; cursor: pointer; transition: border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease; }}
    .task-card:hover {{ transform: translateY(-1px); border-color: #475569; }}
    .task-card.active {{ border-color: var(--blue); box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.4) inset; }}
    .task-title {{ font-size: 16px; font-weight: 650; margin-bottom: 8px; color: white; }}
    .pill-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }}
    .pill {{ display: inline-flex; align-items: center; gap: 8px; border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 650; }}
    .pill.status-completed {{ background: rgba(34, 197, 94, 0.18); color: #bbf7d0; }}
    .pill.status-failed {{ background: rgba(239, 68, 68, 0.18); color: #fecaca; }}
    .pill.status-missing {{ background: rgba(148, 163, 184, 0.18); color: #cbd5e1; }}
    .pill.type {{ color: #0f172a; }}
    .task-meta {{ font-size: 13px; color: var(--muted); }}
    .detail-header {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; align-items: baseline; margin-bottom: 14px; }}
    .detail-title {{ font-size: 24px; font-weight: 700; color: white; }}
    .meta-list {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 16px; margin: 16px 0; }}
    .meta-item strong {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 2px; text-transform: uppercase; letter-spacing: 0.05em; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
    .chip {{ background: rgba(30, 41, 59, 0.85); border: 1px solid var(--border); border-radius: 999px; padding: 4px 10px; font-size: 12px; color: var(--text); }}
    .chat-log {{ margin-top: 16px; display: grid; gap: 8px; max-height: 320px; overflow: auto; padding-right: 4px; }}
    .chat-line {{ padding: 10px 12px; border-radius: 12px; background: rgba(2, 6, 23, 0.7); border: 1px solid rgba(30, 41, 59, 0.8); color: #dbeafe; }}
    .small-note {{ font-size: 13px; color: var(--muted); margin-top: 10px; }}
    .section-spacer {{ margin-top: 20px; }}
    .empty {{ border: 1px dashed var(--border); border-radius: 14px; padding: 20px; color: var(--muted); text-align: center; background: rgba(2, 6, 23, 0.45); }}
    .footer-note {{ margin-top: 20px; color: var(--muted); font-size: 13px; }}
    .summary-inline {{ display: flex; flex-wrap: wrap; gap: 10px 18px; color: var(--muted); font-size: 13px; margin-top: 8px; }}
    @media (max-width: 1100px) {{
      .explorer, .notes {{ grid-template-columns: 1fr; }}
      .toolbar {{ grid-template-columns: 1fr 1fr; }}
      .meta-list {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 700px) {{
      main {{ padding: 18px; }}
      .toolbar {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Voyager Checkpoint Explorer</h1>
    <p>This explorer is generated from the real <code>ckpt_voyager</code> checkpoint. The original run did not come with Replay Mod recordings or exported videos, so the repo now ships a GitHub-friendly visualization site, static charts, and recording utilities.</p>
    <div class=\"hero\">
      <div class=\"card\"><div>Completed Tasks</div><div class=\"metric\">{summary['completed_tasks']}</div></div>
      <div class=\"card\"><div>Failed Tasks</div><div class=\"metric\">{summary['failed_tasks']}</div></div>
      <div class=\"card\"><div>Skills</div><div class=\"metric\">{summary['skills']}</div></div>
      <div class=\"card\"><div>Recorded Episodes</div><div class=\"metric\">{summary['recorded_episodes']}</div></div>
      <div class=\"card\"><div>Recorded Time</div><div class=\"metric\">{summary['recorded_ticks_label']}</div></div>
    </div>
    <div class=\"images\">
      <img src=\"dashboard.svg\" alt=\"Voyager dashboard\" />
      <img src=\"tasks.svg\" alt=\"Voyager task timeline\" />
    </div>
    <section class=\"panel section-spacer\">
      <h2>Interactive Explorer</h2>
      <p>Filter the checkpoint by task status, task type, biome, or free-text search. Click any route node or task card to inspect the final snapshot, inventory, and chat transcript for that step.</p>
      <div class=\"toolbar\">
        <div>
          <label for=\"searchInput\">Search</label>
          <input id=\"searchInput\" type=\"search\" placeholder=\"Search tasks, chat, or items\" />
        </div>
        <div>
          <label for=\"statusFilter\">Status</label>
          <select id=\"statusFilter\"></select>
        </div>
        <div>
          <label for=\"categoryFilter\">Task Type</label>
          <select id=\"categoryFilter\"></select>
        </div>
        <div>
          <label for=\"biomeFilter\">Biome</label>
          <select id=\"biomeFilter\"></select>
        </div>
      </div>
      <div class=\"summary-inline\">
        <div id=\"taskCount\"></div>
        <div>Biomes visited: {', '.join(summary['biomes'])}</div>
        <div>Off-path recorded tasks: {', '.join(summary['off_path_unique_tasks']) if summary['off_path_unique_tasks'] else 'none'}</div>
      </div>
      <div class=\"explorer\">
        <section class=\"panel\">
          <h2>Route Map</h2>
          <p>Each circle is a saved task snapshot projected on the X/Z plane.</p>
          <svg id=\"routeMap\" class=\"route-map\" viewBox=\"0 0 900 560\" preserveAspectRatio=\"none\"></svg>
          <div class=\"legend\">
            <span class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#22c55e\"></span>Completed</span>
            <span class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#ef4444\"></span>Failed</span>
            <span class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#60a5fa\"></span>Mine</span>
            <span class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#f59e0b\"></span>Craft</span>
            <span class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#f97316\"></span>Smelt</span>
            <span class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#10b981\"></span>Equip</span>
            <span class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#a78bfa\"></span>Other</span>
          </div>
        </section>
        <aside class=\"panel\" id=\"detailPanel\"></aside>
      </div>
      <div class=\"section-spacer\">
        <h2>Filtered Tasks</h2>
        <div id=\"taskGrid\" class=\"task-grid\"></div>
      </div>
    </section>
    <div class=\"notes\">
      <div class=\"card\">
          <h2>Item Milestones</h2>
          <table>
            <thead><tr><th>Item</th><th>Episode</th><th>Reached At</th></tr></thead>
            <tbody>
            {milestone_rows}
            </tbody>
          </table>
        </div>
      <div class=\"card\">
          <h2>Latest Inventory Snapshot</h2>
          <table>
            <thead><tr><th>Item</th><th>Count</th></tr></thead>
            <tbody>
            {inventory_rows}
            </tbody>
          </table>
        <p class=\"footer-note\">This page is generated into both <code>demo/</code> and <code>docs/</code>. The <code>docs/</code> copy is intended for GitHub Pages deployment.</p>
      </div>
    </div>
    <script id=\"voyager-data\" type=\"application/json\">{json_payload}</script>
    <script>
      const data = JSON.parse(document.getElementById('voyager-data').textContent);
      const taskGrid = document.getElementById('taskGrid');
      const detailPanel = document.getElementById('detailPanel');
      const routeMap = document.getElementById('routeMap');
      const taskCount = document.getElementById('taskCount');
      const searchInput = document.getElementById('searchInput');
      const statusFilter = document.getElementById('statusFilter');
      const categoryFilter = document.getElementById('categoryFilter');
      const biomeFilter = document.getElementById('biomeFilter');
      const allTasks = data.official_tasks;
      const taskColors = {{ Mine: '#60a5fa', Craft: '#f59e0b', Smelt: '#f97316', Equip: '#10b981', Kill: '#ef4444', Other: '#a78bfa' }};
      const statusColors = {{ completed: '#22c55e', failed: '#ef4444', missing: '#94a3b8' }};
      const state = {{
        search: '',
        status: 'all',
        category: 'all',
        biome: 'all',
        selected: allTasks.find((task) => task.position)?.source_file || allTasks[0]?.source_file || null,
      }};

      function unique(values) {{
        return [...new Set(values)].sort((left, right) => String(left).localeCompare(String(right)));
      }}

      function fillSelect(select, values, label) {{
        const options = ['<option value="all">' + label + '</option>'];
        values.forEach((value) => {{
          options.push('<option value="' + escapeHtml(value) + '">' + escapeHtml(value) + '</option>');
        }});
        select.innerHTML = options.join('');
      }}

      function escapeHtml(value) {{
        return String(value)
          .replaceAll('&', '&amp;')
          .replaceAll('<', '&lt;')
          .replaceAll('>', '&gt;')
          .replaceAll('"', '&quot;')
          .replaceAll("'", '&#39;');
      }}

      fillSelect(statusFilter, unique(allTasks.map((task) => task.status)), 'All statuses');
      fillSelect(categoryFilter, unique(allTasks.map((task) => task.category)), 'All task types');
      fillSelect(biomeFilter, unique(allTasks.map((task) => task.biome).filter((biome) => biome && biome !== 'n/a')), 'All biomes');

      function matchTask(task) {{
        if (state.status !== 'all' && task.status !== state.status) return false;
        if (state.category !== 'all' && task.category !== state.category) return false;
        if (state.biome !== 'all' && task.biome !== state.biome) return false;
        if (!state.search) return true;
        const haystack = [
          task.name,
          task.category,
          task.status,
          task.biome,
          task.time_of_day,
          ...(task.chat_messages || []),
          ...(task.inventory || []).map((item) => item[0]),
        ].join(' ').toLowerCase();
        return haystack.includes(state.search.toLowerCase());
      }}

      function getFilteredTasks() {{
        return allTasks.filter(matchTask);
      }}

      function pickSelected(tasks) {{
        const current = tasks.find((task) => task.source_file === state.selected || task.name === state.selected);
        if (current) return current;
        const fallback = tasks[0] || allTasks[0] || null;
        state.selected = fallback ? (fallback.source_file || fallback.name) : null;
        return fallback;
      }}

      function renderTaskGrid(tasks, selectedTask) {{
        taskCount.textContent = tasks.length + ' / ' + allTasks.length + ' tasks shown';
        if (!tasks.length) {{
          taskGrid.innerHTML = '<div class="empty">No tasks match the current filters.</div>';
          return;
        }}

        taskGrid.innerHTML = tasks.map((task) => {{
          const categoryColor = taskColors[task.category] || taskColors.Other;
          const isActive = selectedTask && (selectedTask.source_file === task.source_file || selectedTask.name === task.name);
          return `
            <button class="task-card${{isActive ? ' active' : ''}}" data-task-id="${{escapeHtml(task.source_file || task.name)}}">
              <div class="task-title">${{escapeHtml(task.index + '. ' + task.name)}}</div>
              <div class="pill-row">
                <span class="pill status-${{escapeHtml(task.status)}}">${{escapeHtml(task.status)}}</span>
                <span class="pill type" style="background:${{categoryColor}}">${{escapeHtml(task.category)}}</span>
              </div>
              <div class="task-meta">${{escapeHtml(task.duration_label)}} in ${{escapeHtml(task.biome)}}</div>
              <div class="task-meta">${{task.position ? 'x=' + task.position.x.toFixed(1) + ', z=' + task.position.z.toFixed(1) : 'No saved position'}}</div>
            </button>
          `;
        }}).join('');

        taskGrid.querySelectorAll('.task-card').forEach((button) => {{
          button.addEventListener('click', () => {{
            state.selected = button.dataset.taskId;
            render();
          }});
        }});
      }}

      function renderDetail(task) {{
        if (!task) {{
          detailPanel.innerHTML = '<div class="empty">No task selected.</div>';
          return;
        }}

        const inventoryChips = (task.inventory || []).map(([name, count]) => `<span class="chip">${{escapeHtml(name)}} x${{count}}</span>`).join('') || '<span class="chip">Inventory unavailable</span>';
        const equipmentChips = (task.equipment || []).filter(Boolean).map((item) => `<span class="chip">${{escapeHtml(item)}}</span>`).join('') || '<span class="chip">No equipment saved</span>';
        const chatLines = (task.chat_messages || []).map((line) => `<div class="chat-line">${{escapeHtml(line)}}</div>`).join('') || '<div class="empty">No chat transcript saved for this task.</div>';
        detailPanel.innerHTML = `
          <div class="detail-header">
            <div>
              <div class="detail-title">${{escapeHtml(task.name)}}</div>
              <div class="summary-inline">
                <div class="status ${{escapeHtml(task.status)}}">${{escapeHtml(task.status)}}</div>
                <div>${{escapeHtml(task.category)}}</div>
                <div>${{escapeHtml(task.duration_label)}}</div>
              </div>
            </div>
            <div class="small-note">${{escapeHtml(task.source_file || 'no source file')}}</div>
          </div>
          <div class="meta-list">
            <div class="meta-item"><strong>Biome</strong><span>${{escapeHtml(task.biome)}}</span></div>
            <div class="meta-item"><strong>Time of Day</strong><span>${{escapeHtml(task.time_of_day)}}</span></div>
            <div class="meta-item"><strong>Position</strong><span>${{task.position ? 'x=' + task.position.x.toFixed(1) + ', z=' + task.position.z.toFixed(1) : 'n/a'}}</span></div>
            <div class="meta-item"><strong>Health / Food</strong><span>${{task.health ?? 'n/a'}} / ${{task.food ?? 'n/a'}}</span></div>
          </div>
          <div>
            <strong style="display:block;color:var(--muted);font-size:12px;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.05em;">Equipment</strong>
            <div class="chips">${{equipmentChips}}</div>
          </div>
          <div class="section-spacer">
            <strong style="display:block;color:var(--muted);font-size:12px;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.05em;">Inventory</strong>
            <div class="chips">${{inventoryChips}}</div>
          </div>
          <div class="section-spacer">
            <strong style="display:block;color:var(--muted);font-size:12px;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.05em;">Chat Transcript</strong>
            <div class="chat-log">${{chatLines}}</div>
          </div>
        `;
      }}

      function renderMap(tasks, selectedTask) {{
        const points = tasks.filter((task) => task.position);
        if (!points.length) {{
          routeMap.innerHTML = '<foreignObject x="0" y="0" width="900" height="560"><div xmlns="http://www.w3.org/1999/xhtml" class="empty" style="height:100%;display:flex;align-items:center;justify-content:center;">No route points available for the current filters.</div></foreignObject>';
          return;
        }}

        const pad = 40;
        const width = 900;
        const height = 560;
        const xs = points.map((task) => task.position.x);
        const zs = points.map((task) => task.position.z);
        let minX = Math.min(...xs);
        let maxX = Math.max(...xs);
        let minZ = Math.min(...zs);
        let maxZ = Math.max(...zs);
        if (Math.abs(maxX - minX) < 1e-6) maxX += 1;
        if (Math.abs(maxZ - minZ) < 1e-6) maxZ += 1;

        function scale(task) {{
          const x = pad + ((task.position.x - minX) / (maxX - minX)) * (width - pad * 2);
          const y = pad + (1 - (task.position.z - minZ) / (maxZ - minZ)) * (height - pad * 2);
          return [x, y];
        }}

        const grid = [];
        for (let i = 0; i <= 4; i += 1) {{
          const gx = pad + ((width - pad * 2) / 4) * i;
          const gy = pad + ((height - pad * 2) / 4) * i;
          grid.push(`<line x1="${{gx}}" y1="${{pad}}" x2="${{gx}}" y2="${{height - pad}}" stroke="#1f2937" stroke-width="1" />`);
          grid.push(`<line x1="${{pad}}" y1="${{gy}}" x2="${{width - pad}}" y2="${{gy}}" stroke="#1f2937" stroke-width="1" />`);
        }}

        const polyline = points.map((task) => scale(task).join(',')).join(' ');
        const nodes = points.map((task) => {{
          const [x, y] = scale(task);
          const selected = selectedTask && (selectedTask.source_file === task.source_file || selectedTask.name === task.name);
          const fill = statusColors[task.status] || '#94a3b8';
          const stroke = taskColors[task.category] || taskColors.Other;
          const radius = selected ? 10 : 7;
          return `<g class="route-node" data-task-id="${{escapeHtml(task.source_file || task.name)}}" style="cursor:pointer"><circle cx="${{x}}" cy="${{y}}" r="${{radius}}" fill="${{fill}}" stroke="${{stroke}}" stroke-width="3" /><title>${{escapeHtml(task.name)}} - ${{escapeHtml(task.status)}}</title></g>`;
        }}).join('');
        const [startX, startY] = scale(points[0]);
        const [endX, endY] = scale(points[points.length - 1]);
        routeMap.innerHTML = `
          <rect x="0" y="0" width="900" height="560" fill="transparent"></rect>
          ${{grid.join('')}}
          <polyline points="${{polyline}}" fill="none" stroke="#60a5fa" stroke-width="4" stroke-linejoin="round" stroke-linecap="round" opacity="0.86"></polyline>
          ${{nodes}}
          <circle cx="${{startX}}" cy="${{startY}}" r="12" fill="#22c55e" stroke="#ecfeff" stroke-width="2"></circle>
          <circle cx="${{endX}}" cy="${{endY}}" r="12" fill="#f59e0b" stroke="#ecfeff" stroke-width="2"></circle>
          <text x="${{startX + 14}}" y="${{startY - 12}}" fill="#d1fae5" font-size="13" font-weight="700">Start</text>
          <text x="${{endX + 14}}" y="${{endY - 12}}" fill="#fde68a" font-size="13" font-weight="700">Latest</text>
          <text x="40" y="536" fill="#64748b" font-size="12">X ${{minX.toFixed(1)}} to ${{maxX.toFixed(1)}} | Z ${{minZ.toFixed(1)}} to ${{maxZ.toFixed(1)}}</text>
        `;

        routeMap.querySelectorAll('.route-node').forEach((node) => {{
          node.addEventListener('click', () => {{
            state.selected = node.dataset.taskId;
            render();
          }});
        }});
      }}

      function render() {{
        const tasks = getFilteredTasks();
        const selectedTask = pickSelected(tasks);
        renderTaskGrid(tasks, selectedTask);
        renderDetail(selectedTask);
        renderMap(tasks, selectedTask);
      }}

      searchInput.addEventListener('input', () => {{ state.search = searchInput.value.trim(); render(); }});
      statusFilter.addEventListener('change', () => {{ state.status = statusFilter.value; render(); }});
      categoryFilter.addEventListener('change', () => {{ state.category = categoryFilter.value; render(); }});
      biomeFilter.addEventListener('change', () => {{ state.biome = biomeFilter.value; render(); }});
      render();
    </script>
  </main>
</body>
</html>
"""


def main() -> None:
    data = build_summary_data()
    written_dirs = []
    for output_dir in OUTPUT_DIRS:
        output_dir.mkdir(exist_ok=True)
        with open(output_dir / "data.json", "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        with open(output_dir / "dashboard.svg", "w", encoding="utf-8") as handle:
            handle.write(render_dashboard_svg(data))
        with open(output_dir / "tasks.svg", "w", encoding="utf-8") as handle:
            handle.write(render_tasks_svg(data))
        with open(output_dir / "index.html", "w", encoding="utf-8") as handle:
            handle.write(render_html(data))
        written_dirs.append(str(output_dir))

    print(f"Wrote demo assets to {', '.join(written_dirs)}")


if __name__ == "__main__":
    main()
