#!/usr/bin/env python3
"""Download and install a Replay Mod jar into ~/.minecraft/mods."""

from __future__ import annotations

import argparse
import shutil
import urllib.request
from pathlib import Path


DEFAULT_VERSION = "1.19-2.6.26"
DEFAULT_MINECRAFT_DIR = Path.home() / ".minecraft"


def download_replaymod(version: str, output_path: Path) -> None:
    url = f"https://www.replaymod.com/download/download_new.php?version={version}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, open(output_path, "wb") as handle:
        shutil.copyfileobj(response, handle)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION, help="Replay Mod version string")
    parser.add_argument(
        "--minecraft-dir",
        default=str(DEFAULT_MINECRAFT_DIR),
        help="Minecraft home directory containing mods/",
    )
    parser.add_argument(
        "--cache-dir",
        default="downloads/replaymod",
        help="Where to cache downloaded jars before install",
    )
    args = parser.parse_args()

    minecraft_dir = Path(args.minecraft_dir).expanduser().resolve()
    mods_dir = minecraft_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = Path(args.cache_dir).resolve()
    jar_name = f"replaymod-{args.version}.jar"
    cached_jar = cache_dir / jar_name
    target_jar = mods_dir / jar_name

    print(f"Downloading Replay Mod {args.version} to {cached_jar}")
    download_replaymod(args.version, cached_jar)
    shutil.copy2(cached_jar, target_jar)

    print(f"Installed Replay Mod to {target_jar}")
    print("Replay Mod records sessions automatically when recording is enabled in its settings.")
    print("Install ffmpeg as well if you want to render Replay Mod recordings to video.")


if __name__ == "__main__":
    main()
