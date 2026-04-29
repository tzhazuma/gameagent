#!/usr/bin/env python3
"""
Quick-start Voyager runner for short smoke tests.

Usage:
  1. Launch Minecraft 1.19 Fabric manually:
     python3 launch_mc.py
  2. Open your world to LAN with cheats enabled.
  3. Run this script with the LAN port:
     python3 run.py <port>
"""

import os
import sys


def load_local_env(file_name=".env.local"):
    env_path = os.path.join(os.path.dirname(__file__), file_name)
    if not os.path.exists(env_path):
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


def clear_proxy_env():
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(key, None)


load_local_env()
clear_proxy_env()

if not os.environ.get("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY must be set in the environment")

os.environ.setdefault("OPENAI_API_BASE", "https://opencode.ai/zen/go/v1")

if len(sys.argv) < 2:
    print("Usage: python3 run.py <LAN_PORT>")
    print("  LAN_PORT: the port shown in Minecraft after opening the world to LAN")
    sys.exit(1)

port = int(sys.argv[1])
model_name = os.environ.get("VOYAGER_MODEL_NAME", "kimi-k2.6")

print(f"Starting Voyager smoke test on LAN port {port}...")
print(f"Model: {model_name}")
print("API: opencode-compatible endpoint")

from voyager import Voyager

voyager = Voyager(
    mc_port=port,
    server_port=3000,
    openai_api_key=os.environ["OPENAI_API_KEY"],
    openai_api_base=os.environ["OPENAI_API_BASE"],
    action_agent_model_name=model_name,
    curriculum_agent_model_name=model_name,
    curriculum_agent_qa_model_name=model_name,
    critic_agent_model_name=model_name,
    skill_manager_model_name=model_name,
    ckpt_dir="ckpt_voyager",
    resume=False,
    max_iterations=5,
    env_wait_ticks=20,
    env_request_timeout=300,
    openai_api_request_timeout=240,
)

print("Voyager initialized. Starting lifelong learning...")
print("(Press Ctrl+C to stop at any time)")
print()

try:
    result = voyager.learn()
    print("\n=== Voyager Complete ===")
    print(f"Completed tasks: {result['completed_tasks']}")
    print(f"Failed tasks: {result['failed_tasks']}")
    print(f"Skills learned: {len(result['skills'])}")
except KeyboardInterrupt:
    print("\nStopped by user.")
except Exception as e:
    print(f"\nError: {e}")
    import traceback

    traceback.print_exc()
finally:
    try:
        voyager.close()
    except Exception:
        pass
