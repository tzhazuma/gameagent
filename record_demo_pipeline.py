#!/usr/bin/env python3
"""Run the full local demo pipeline: server, Voyager, viewer capture, and cleanup."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


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


def parse_size(value: str) -> tuple[int, int]:
    parts = value.lower().split("x", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT")
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT") from exc
    return width, height


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="recordings/voyager-demo.mp4",
        help="Final cleaned MP4 output path",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=240,
        help="Capture duration in seconds",
    )
    parser.add_argument(
        "--viewer-port",
        type=int,
        default=3007,
        help="Prismarine viewer port",
    )
    parser.add_argument(
        "--mc-port",
        type=int,
        default=25565,
        help="Local Minecraft demo server port",
    )
    parser.add_argument(
        "--display",
        default=":98",
        help="Xvfb display name",
    )
    parser.add_argument(
        "--size",
        type=parse_size,
        default=(1280, 720),
        help="Capture size as WIDTHxHEIGHT",
    )
    parser.add_argument(
        "--crop-top",
        type=int,
        default=150,
        help="Pixels cropped from the top before scaling back to the target size",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=120,
        help="Viewer wait timeout in seconds",
    )
    parser.add_argument(
        "--page-settle-seconds",
        type=int,
        default=5,
        help="Browser settle time before capture starts",
    )
    parser.add_argument(
        "--ckpt-dir",
        default="ckpt_recorded_demo_long",
        help="Checkpoint directory used for the recorded run",
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
        default="direct",
        help="Use direct learned-skill replay or the full action agent loop",
    )
    return parser


def wait_for_ready_file(ready_file: Path, timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ready_file.exists():
            return
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {ready_file}")


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


def run_ffmpeg_crop(source: Path, target: Path, width: int, height: int, crop_top: int) -> None:
    crop_height = height - crop_top
    if crop_height <= 0:
        raise ValueError("crop-top must be smaller than the capture height")
    temp_target = target.with_name(target.stem + ".cropped" + target.suffix)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vf",
        f"crop={width}:{crop_height}:0:{crop_top},scale={width}:{height}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(temp_target),
    ]
    subprocess.run(command, check=True)
    temp_target.replace(target)


def main() -> None:
    args = build_parser().parse_args()
    clear_proxy_env()

    root = Path(__file__).resolve().parent
    ready_file = root / ".demo_server" / "ready.json"
    output_path = (root / args.output).resolve()
    ckpt_path = (root / args.ckpt_dir).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_output = output_path.with_name(output_path.stem + ".raw" + output_path.suffix)
    server_log = output_path.with_name(output_path.stem + "-server.log")
    run_log = output_path.with_name(output_path.stem + "-run.log")
    done_file = output_path.with_name(output_path.stem + ".done")
    width, height = args.size

    if ready_file.exists():
        ready_file.unlink()
    if ckpt_path.exists():
        shutil.rmtree(ckpt_path, ignore_errors=True)
    for path in (output_path, raw_output, server_log, run_log, done_file):
        if path.exists():
            path.unlink()

    server_proc = None
    run_proc = None
    run_incomplete = False
    try:
        with open(server_log, "w", encoding="utf-8") as server_handle:
            server_proc = subprocess.Popen(
                [
                    sys.executable,
                    "start_demo_server.py",
                    "--fresh-world",
                    "--port",
                    str(args.mc_port),
                ],
                cwd=root,
                stdout=server_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        wait_for_ready_file(ready_file, 180)

        env = dict(os.environ)
        env["VOYAGER_VIEWER_PORT"] = str(args.viewer_port)
        env["VOYAGER_VIEWER_DRAW_PATH"] = "1"

        with open(run_log, "w", encoding="utf-8") as run_handle:
            run_proc = subprocess.Popen(
                [
                    sys.executable,
                "run_recorded_demo.py",
                str(args.mc_port),
                "--ckpt-dir",
                args.ckpt_dir,
                "--mode",
                args.mode,
                "--done-file",
                str(done_file),
                "--reset-mode",
                "soft",
                "--tasks",
                *args.tasks,
                ],
                cwd=root,
                env=env,
                stdout=run_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )

        viewer_url = f"http://127.0.0.1:{args.viewer_port}/"
        subprocess.run(
            [
                sys.executable,
                "capture_viewer.py",
                viewer_url,
                str(raw_output),
                "--duration",
                str(args.duration),
                "--wait-timeout",
                str(args.wait_timeout),
                "--page-settle-seconds",
                str(args.page_settle_seconds),
                "--stop-when-file-exists",
                str(done_file),
                "--display",
                args.display,
                "--size",
                f"{width}x{height}",
            ],
            cwd=root,
            check=True,
        )

        if run_proc.poll() is None:
            run_incomplete = True
            interrupt_process(run_proc)

        if args.crop_top > 0:
            run_ffmpeg_crop(raw_output, output_path, width, height, args.crop_top)
            raw_output.unlink(missing_ok=True)
        else:
            raw_output.replace(output_path)

        print(f"Wrote cleaned recording to {output_path}")
        print(f"Run log: {run_log}")
        print(f"Server log: {server_log}")
        if run_incomplete:
            print("Warning: capture ended before the recorded task sequence finished; increase --duration to capture the full run.")
    finally:
        interrupt_process(run_proc)
        interrupt_process(server_proc)


if __name__ == "__main__":
    main()
