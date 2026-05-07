#!/usr/bin/env python3
"""Capture the prismarine viewer page to an MP4 using Chromium and Xvfb."""

from __future__ import annotations

import argparse
import math
import os
import signal
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


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


def wait_for_url(url: str, timeout: float) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
        except Exception:
            time.sleep(1)
            continue
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}")


def capture_display_frame(display: str, size: str, output_path: Path) -> bool:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-video_size",
        size,
        "-framerate",
        "1",
        "-f",
        "x11grab",
        "-i",
        display,
        "-frames:v",
        "1",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return completed.returncode == 0 and output_path.exists()


def capture_display_frame_ppm(display: str, size: str) -> bytes | None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-video_size",
        size,
        "-framerate",
        "1",
        "-f",
        "x11grab",
        "-i",
        display,
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "ppm",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0 or not completed.stdout:
        return None
    return completed.stdout


def parse_ppm_frame(payload: bytes) -> tuple[int, int, memoryview] | None:
    index = 0
    tokens: list[bytes] = []
    payload_length = len(payload)

    while len(tokens) < 4 and index < payload_length:
        while index < payload_length and chr(payload[index]).isspace():
            index += 1
        if index >= payload_length:
            break
        if payload[index:index + 1] == b"#":
            newline = payload.find(b"\n", index)
            if newline == -1:
                return None
            index = newline + 1
            continue
        end = index
        while end < payload_length and not chr(payload[end]).isspace():
            end += 1
        tokens.append(payload[index:end])
        index = end

    if len(tokens) != 4 or tokens[0] != b"P6":
        return None

    try:
        width = int(tokens[1])
        height = int(tokens[2])
        max_value = int(tokens[3])
    except ValueError:
        return None

    if width <= 0 or height <= 0 or max_value != 255:
        return None

    while index < payload_length and chr(payload[index]).isspace():
        index += 1

    pixel_data = memoryview(payload)[index:]
    expected_length = width * height * 3
    if len(pixel_data) < expected_length:
        return None
    return width, height, pixel_data[:expected_length]


def sampled_render_metrics(
    display: str,
    size: str,
    *,
    crop_top: int,
) -> tuple[float, float] | None:
    payload = capture_display_frame_ppm(display, size)
    if payload is None:
        return None
    frame = parse_ppm_frame(payload)
    if frame is None:
        return None

    width, height, pixel_data = frame
    top = min(max(crop_top, 0), max(height - 1, 0))
    available_height = height - top
    if available_height <= 0:
        return None

    inset_x = width // 10
    inset_y = available_height // 10
    left = inset_x
    right = width - inset_x
    sample_top = top + inset_y
    bottom = height - inset_y
    if right <= left or bottom <= sample_top:
        left = 0
        right = width
        sample_top = top
        bottom = height

    count = 0
    black_pixels = 0
    sum_red = 0.0
    sum_green = 0.0
    sum_blue = 0.0
    sumsq_red = 0.0
    sumsq_green = 0.0
    sumsq_blue = 0.0

    for y in range(sample_top, bottom):
        row_start = (y * width + left) * 3
        row_end = (y * width + right) * 3
        row = pixel_data[row_start:row_end]
        for offset in range(0, len(row), 3):
            red = row[offset]
            green = row[offset + 1]
            blue = row[offset + 2]
            count += 1
            sum_red += red
            sum_green += green
            sum_blue += blue
            sumsq_red += red * red
            sumsq_green += green * green
            sumsq_blue += blue * blue
            if red < 24 and green < 24 and blue < 24:
                black_pixels += 1

    if count == 0:
        return None

    mean_red = sum_red / count
    mean_green = sum_green / count
    mean_blue = sum_blue / count
    stddev_red = math.sqrt(max(sumsq_red / count - mean_red * mean_red, 0.0))
    stddev_green = math.sqrt(max(sumsq_green / count - mean_green * mean_green, 0.0))
    stddev_blue = math.sqrt(max(sumsq_blue / count - mean_blue * mean_blue, 0.0))
    max_stddev = max(stddev_red, stddev_green, stddev_blue)
    black_percent = black_pixels * 100 / count
    return black_percent, max_stddev


def is_rendered_viewer_ready(
    metrics: tuple[float, float] | None,
    *,
    black_threshold: float,
    min_stddev: float,
) -> bool:
    if metrics is None:
        return False
    black_percent, stddev = metrics
    return black_percent < black_threshold and stddev >= min_stddev


def wait_for_rendered_viewer(
    display: str,
    size: str,
    timeout: float,
    black_threshold: float,
    min_stddev: float,
    crop_top: int,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        metrics = sampled_render_metrics(display, size, crop_top=crop_top)
        if is_rendered_viewer_ready(metrics, black_threshold=black_threshold, min_stddev=min_stddev):
            return
        time.sleep(1)
    raise RuntimeError(
        f"Timed out waiting for viewer to render non-black frames on display {display}"
    )


def positive_int_or_zero(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def chromium_binary() -> str:
    for candidate in ("chromium-browser", "chromium", "google-chrome", "google-chrome-stable"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("Could not find a Chromium-based browser")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Viewer URL to open")
    parser.add_argument("output", help="Output MP4 path")
    parser.add_argument("--duration", type=float, default=90, help="Capture duration in seconds")
    parser.add_argument("--display", default=":98", help="Xvfb display name")
    parser.add_argument("--size", default="1280x720", help="Capture size as WIDTHxHEIGHT")
    parser.add_argument("--fps", type=int, default=30, help="Capture frame rate")
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=90,
        help="How long to wait for the viewer URL before giving up",
    )
    parser.add_argument(
        "--page-settle-seconds",
        type=float,
        default=6,
        help="How long to wait after the page opens before recording starts",
    )
    parser.add_argument(
        "--render-timeout",
        type=positive_float,
        default=30,
        help="How long to wait for non-black rendered viewer frames after opening the page",
    )
    parser.add_argument(
        "--render-black-threshold",
        type=non_negative_float,
        default=98,
        help="Treat the viewer as ready once sampled frames are below this black percentage",
    )
    parser.add_argument(
        "--render-min-stddev",
        type=non_negative_float,
        default=8,
        help="Require at least this much post-crop frame variance before capture starts",
    )
    parser.add_argument(
        "--sample-crop-top",
        type=positive_int_or_zero,
        default=150,
        help="Ignore this many pixels from the top when checking if the viewer has rendered",
    )
    parser.add_argument(
        "--stop-when-file-exists",
        help="Optional path whose creation stops recording early",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    clear_proxy_env()
    width, height = args.size.lower().split("x", 1)
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wait_for_url(args.url, args.wait_timeout)
    stop_file = Path(args.stop_when_file_exists).resolve() if args.stop_when_file_exists else None

    with tempfile.TemporaryDirectory(prefix="voyager-chromium-") as profile_dir:
        xvfb = subprocess.Popen(
            ["Xvfb", args.display, "-screen", "0", f"{width}x{height}x24", "-ac"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        browser = None
        ffmpeg = None
        try:
            time.sleep(2)
            env = dict(os.environ)
            env["DISPLAY"] = args.display
            browser = subprocess.Popen(
                [
                    chromium_binary(),
                    "--no-sandbox",
                    "--no-proxy-server",
                    "--use-gl=swiftshader",
                    "--enable-unsafe-swiftshader",
                    "--ignore-gpu-blocklist",
                    f"--user-data-dir={profile_dir}",
                    "--new-window",
                    f"--window-size={width},{height}",
                    args.url,
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(args.page_settle_seconds)
            wait_for_rendered_viewer(
                args.display,
                args.size,
                args.render_timeout,
                args.render_black_threshold,
                args.render_min_stddev,
                args.sample_crop_top,
            )
            ffmpeg_command = [
                "ffmpeg",
                "-y",
                "-video_size",
                f"{width}x{height}",
                "-framerate",
                str(args.fps),
                "-f",
                "x11grab",
                "-i",
                args.display,
                "-t",
                str(args.duration),
                "-pix_fmt",
                "yuv420p",
                "-vcodec",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
            ffmpeg = subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE, text=True)
            stop_requested = False
            while ffmpeg.poll() is None:
                if stop_file is not None and stop_file.exists() and not stop_requested:
                    stop_requested = True
                    if ffmpeg.stdin is not None:
                        try:
                            ffmpeg.stdin.write("q\n")
                            ffmpeg.stdin.flush()
                        except BrokenPipeError:
                            pass
                    else:
                        ffmpeg.send_signal(signal.SIGINT)
                time.sleep(1)
            if ffmpeg.returncode not in (0, None):
                raise subprocess.CalledProcessError(ffmpeg.returncode, ffmpeg_command)
        finally:
            if ffmpeg is not None and ffmpeg.poll() is None:
                ffmpeg.terminate()
                try:
                    ffmpeg.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    ffmpeg.kill()
            if browser is not None and browser.poll() is None:
                browser.terminate()
                try:
                    browser.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    browser.kill()
            if xvfb.poll() is None:
                xvfb.terminate()
                try:
                    xvfb.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    xvfb.kill()


if __name__ == "__main__":
    main()
