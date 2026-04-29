#!/usr/bin/env python3
"""Generate a static visual demo from ckpt_voyager event logs."""

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
OUTPUT_DIR = ROOT / "demo"

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
    milestone_rows = "\n".join(
        f"<tr><td>{html.escape(m['item'])}</td><td>{html.escape(m['task_key'])}</td><td>{html.escape(m['label'])}</td></tr>"
        for m in data["item_milestones"][:20]
    )
    task_rows = "\n".join(
        "<tr>"
        f"<td>{row['index']}</td>"
        f"<td>{html.escape(row['name'])}</td>"
        f"<td>{html.escape(row['category'])}</td>"
        f"<td class=\"status {row['status']}\">{html.escape(row['status'])}</td>"
        f"<td>{html.escape(row['duration_label'])}</td>"
        f"<td>{html.escape(row['biome'])}</td>"
        "</tr>"
        for row in data["official_tasks"]
    )

    summary = data["summary"]
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Voyager Demo</title>
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
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font: 15px/1.5 Inter, Segoe UI, Arial, sans-serif; background: linear-gradient(180deg, #020617 0%, #0f172a 100%); color: var(--text); }}
    main {{ max-width: 1380px; margin: 0 auto; padding: 32px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    p {{ margin: 0 0 16px; color: var(--muted); }}
    .hero {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin: 24px 0; }}
    .card {{ background: rgba(15, 23, 42, 0.9); border: 1px solid var(--border); border-radius: 18px; padding: 18px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25); }}
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
    @media (max-width: 900px) {{ .notes {{ grid-template-columns: 1fr; }} main {{ padding: 18px; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Voyager Minecraft Demo</h1>
    <p>This standalone page is generated from the real <code>ckpt_voyager</code> checkpoint. Replay Mod assets were not present in this workspace, so this repo now includes a checkpoint-driven visual demo that can be committed and shared directly.</p>
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
    <div class=\"notes\">
      <div class=\"card\">
        <h2>Official Tasks</h2>
        <table>
          <thead><tr><th>#</th><th>Task</th><th>Type</th><th>Status</th><th>Duration</th><th>Biome</th></tr></thead>
          <tbody>
            {task_rows}
          </tbody>
        </table>
      </div>
      <div class=\"card\">
        <h2>Item Milestones</h2>
        <table>
          <thead><tr><th>Item</th><th>Episode</th><th>Reached At</th></tr></thead>
          <tbody>
            {milestone_rows}
          </tbody>
        </table>
      </div>
    </div>
  </main>
</body>
</html>
"""


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    data = build_summary_data()

    with open(OUTPUT_DIR / "data.json", "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    with open(OUTPUT_DIR / "dashboard.svg", "w", encoding="utf-8") as handle:
        handle.write(render_dashboard_svg(data))
    with open(OUTPUT_DIR / "tasks.svg", "w", encoding="utf-8") as handle:
        handle.write(render_tasks_svg(data))
    with open(OUTPUT_DIR / "index.html", "w", encoding="utf-8") as handle:
        handle.write(render_html(data))

    print(f"Wrote demo assets to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
