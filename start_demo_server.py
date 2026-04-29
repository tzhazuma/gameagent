#!/usr/bin/env python3
"""Start a local offline Minecraft server with a small Voyager demo arena."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import uuid
import urllib.request
from pathlib import Path


SERVER_URL = "https://piston-data.mojang.com/v1/objects/e00c4052dac1d59a1188b2aa9d5a87113aaf1122/server.jar"
SERVER_SHA1 = "e00c4052dac1d59a1188b2aa9d5a87113aaf1122"
DEFAULT_ROOT = Path(".demo_server")
ARENA_Y = 80


def sha1sum(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def offline_uuid(name: str) -> str:
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def ensure_server_jar(root: Path, force_download: bool) -> Path:
    jar_path = root / "server.jar"
    if force_download or not jar_path.exists() or sha1sum(jar_path) != SERVER_SHA1:
        root.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(SERVER_URL) as response, open(jar_path, "wb") as handle:
            handle.write(response.read())
        if sha1sum(jar_path) != SERVER_SHA1:
            raise RuntimeError("Downloaded server.jar did not match the expected SHA1")
    return jar_path


def reset_world(root: Path) -> None:
    for name in ("world", "world_nether", "world_the_end", "logs", "crash-reports"):
        target = root / name
        if target.exists():
            shutil.rmtree(target)
    for name in ("server.log", "ready.json", "usercache.json"):
        target = root / name
        if target.exists():
            target.unlink()


def write_support_files(root: Path, port: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    server_properties = "\n".join(
        [
            "allow-flight=true",
            "difficulty=peaceful",
            "enable-command-block=true",
            "enable-rcon=false",
            "enforce-secure-profile=false",
            "force-gamemode=false",
            "gamemode=creative",
            "generate-structures=false",
            "level-seed=voyager-demo",
            "level-type=minecraft:flat",
            "max-tick-time=-1",
            "motd=Voyager Demo Server",
            "online-mode=false",
            "pvp=false",
            f"server-port={port}",
            "simulation-distance=6",
            "spawn-protection=0",
            "view-distance=6",
            "white-list=false",
            "",
        ]
    )
    (root / "server.properties").write_text(server_properties, encoding="utf-8")
    ops = [
        {
            "uuid": offline_uuid("bot"),
            "name": "bot",
            "level": 4,
            "bypassesPlayerLimit": False,
        }
    ]
    (root / "ops.json").write_text(json.dumps(ops, indent=2) + "\n", encoding="utf-8")


def send_command(process: subprocess.Popen[str], command: str) -> None:
    if process.stdin is None:
        raise RuntimeError("Server stdin is unavailable")
    process.stdin.write(command + "\n")
    process.stdin.flush()


def prepare_arena(process: subprocess.Popen[str], ready_file: Path, port: int) -> None:
    commands = [
        "gamerule commandBlockOutput false",
        "gamerule doDaylightCycle false",
        "gamerule doWeatherCycle false",
        "gamerule doMobSpawning false",
        "gamerule fallDamage false",
        "gamerule keepInventory true",
        "time set noon",
        "weather clear",
        f"fill -12 {ARENA_Y} -12 12 {ARENA_Y} 12 grass_block",
        f"fill -12 {ARENA_Y + 1} -12 12 {ARENA_Y + 12} 12 air",
        f"setblock -6 {ARENA_Y + 1} 0 spruce_log",
        f"setblock -5 {ARENA_Y + 1} 0 spruce_log",
        f"setblock -4 {ARENA_Y + 1} 0 spruce_log",
        f"setblock -3 {ARENA_Y + 1} 0 spruce_log",
        f"setblock 3 {ARENA_Y + 1} 0 spruce_log",
        f"setblock 4 {ARENA_Y + 1} 0 spruce_log",
        f"setblock 5 {ARENA_Y + 1} 0 spruce_log",
        f"setblock -6 {ARENA_Y + 1} 4 stone",
        f"setblock -5 {ARENA_Y + 1} 4 stone",
        f"setblock -4 {ARENA_Y + 1} 4 stone",
        f"setblock -3 {ARENA_Y + 1} 4 stone",
        f"setblock 0 {ARENA_Y + 1} 2 crafting_table",
        f"setblock 3 {ARENA_Y + 1} 4 stone",
        f"setblock 4 {ARENA_Y + 1} 4 stone",
        f"setblock 5 {ARENA_Y + 1} 4 stone",
        f"setblock 6 {ARENA_Y + 1} 4 stone",
        f"setblock -1 {ARENA_Y + 1} 6 stone",
        f"setblock 0 {ARENA_Y + 1} 6 stone",
        f"setblock 1 {ARENA_Y + 1} 6 stone",
        f"setblock 2 {ARENA_Y + 1} 6 stone",
        f"setworldspawn 0 {ARENA_Y + 1} 0",
    ]
    for command in commands:
        send_command(process, command)
    ready_payload = {
        "port": port,
        "position": {"x": 0.5, "y": float(ARENA_Y + 1), "z": 0.5},
    }
    ready_file.write_text(json.dumps(ready_payload, indent=2) + "\n", encoding="utf-8")
    print(f"DEMO_SERVER_READY {ready_payload}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=25565, help="Minecraft server port")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="Directory used for the local demo server",
    )
    parser.add_argument(
        "--ready-file",
        type=Path,
        default=DEFAULT_ROOT / "ready.json",
        help="File written once the server and demo arena are ready",
    )
    parser.add_argument(
        "--java",
        default="java",
        help="Java executable used to start the server",
    )
    parser.add_argument(
        "--memory",
        default="2G",
        help="Java heap size passed as both -Xms and -Xmx",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Always re-download server.jar",
    )
    parser.add_argument(
        "--fresh-world",
        action="store_true",
        help="Delete the existing demo world before starting",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    ready_file = args.ready_file.resolve()
    log_path = root / "server.log"
    if ready_file.exists():
        ready_file.unlink()

    if args.fresh_world:
        reset_world(root)

    write_support_files(root, args.port)
    jar_path = ensure_server_jar(root, args.force_download)

    command = [
        args.java,
        f"-Xms{args.memory}",
        f"-Xmx{args.memory}",
        "-jar",
        str(jar_path),
        "nogui",
    ]
    print(f"Starting demo server in {root}")
    process = subprocess.Popen(
        command,
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    ready = False
    with open(log_path, "a", encoding="utf-8") as log_file:
        try:
            while True:
                line = process.stdout.readline() if process.stdout else ""
                if not line:
                    if process.poll() is not None:
                        return process.returncode or 0
                    time.sleep(0.1)
                    continue
                print(line, end="")
                log_file.write(line)
                log_file.flush()
                if not ready and "Done (" in line:
                    ready = True
                    prepare_arena(process, ready_file, args.port)
        except KeyboardInterrupt:
            print("Stopping demo server...")
            try:
                send_command(process, "stop")
            except Exception:
                process.terminate()
            process.wait(timeout=30)
            return 0


if __name__ == "__main__":
    sys.exit(main())
