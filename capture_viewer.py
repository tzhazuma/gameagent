#!/usr/bin/env python3
"""Capture the prismarine viewer page to an MP4 using Chromium and Xvfb."""

from __future__ import annotations

import argparse
import os
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
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with opener.open(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
        except Exception:
            time.sleep(1)
            continue
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}")


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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    clear_proxy_env()
    width, height = args.size.lower().split("x", 1)
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wait_for_url(args.url, args.wait_timeout)

    with tempfile.TemporaryDirectory(prefix="voyager-chromium-") as profile_dir:
        xvfb = subprocess.Popen(
            ["Xvfb", args.display, "-screen", "0", f"{width}x{height}x24", "-ac"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        browser = None
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
            subprocess.run(ffmpeg_command, check=True)
        finally:
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
