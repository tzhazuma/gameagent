#!/usr/bin/env python3
"""
Launch Minecraft 1.19 Fabric client for Voyager using a verified classpath.
"""

import glob
import os
import subprocess
import sys
import time


MC_DIR = os.path.expanduser("~/.minecraft")
MC_VERSION = "fabric-loader-0.14.18-1.19"
JAVA_BIN = os.path.join(
    MC_DIR, "runtime", "java-runtime-gamma", "linux", "java-runtime-gamma", "bin", "java"
)


def build_command():
    libs = glob.glob(f"{MC_DIR}/libraries/**/*.jar", recursive=True)
    cp_parts = [
        f"{MC_DIR}/versions/{MC_VERSION}/{MC_VERSION}.jar",
        f"{MC_DIR}/versions/1.19/1.19.jar",
        *libs,
    ]
    # Fabric already ships as the version jar above. Keep it only once.
    cp_parts = [
        p
        for p in cp_parts
        if "fabric-loader/0.14.18/fabric-loader-0.14.18.jar" not in p
    ]
    natives_dir = f"{MC_DIR}/versions/{MC_VERSION}/natives"
    os.makedirs(natives_dir, exist_ok=True)
    return [
        JAVA_BIN,
        "-Xmx3G",
        "-Xms1G",
        "-XX:+UseG1GC",
        "-Dorg.lwjgl.opengl.Display.allowSoftwareOpenGL=true",
        f"-Djava.library.path={natives_dir}",
        "-Dminecraft.launcher.brand=minecraft-launcher-lib",
        "-Dminecraft.launcher.version=8.0",
        "-cp",
        ":".join(cp_parts),
        "net.fabricmc.loader.impl.launch.knot.KnotClient",
        "--username",
        "Player",
        "--version",
        MC_VERSION,
        "--gameDir",
        MC_DIR,
        "--assetsDir",
        f"{MC_DIR}/assets",
        "--assetIndex",
        "1.19",
        "--uuid",
        "00000000000000000000000000000000",
        "--accessToken",
        "0",
        "--clientId",
        "0",
        "--xuid",
        "0",
        "--userType",
        "msa",
        "--versionType",
        "release",
    ]


def main():
    print(f"Launching Minecraft {MC_VERSION}")
    print(f"Java: {JAVA_BIN}")
    print(f"Minecraft dir: {MC_DIR}")
    print()
    print("After launch:")
    print("  1. Singleplayer -> enter your world")
    print("  2. ESC -> Open to LAN")
    print("  3. Turn Allow Cheats ON and Start LAN World")
    print("  4. Tell me the port shown in chat")
    print()

    if not os.path.exists(JAVA_BIN):
        print(f"Missing Java runtime: {JAVA_BIN}", file=sys.stderr)
        sys.exit(1)

    cmd = build_command()
    proc = subprocess.Popen(cmd)
    time.sleep(8)
    if proc.poll() is not None:
        print(f"Minecraft exited early with code {proc.returncode}", file=sys.stderr)
        sys.exit(proc.returncode or 1)
    print(f"Minecraft running with PID {proc.pid}")


if __name__ == "__main__":
    main()
