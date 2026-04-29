#!/usr/bin/env python3
"""
Voyager runner with file logging
Run this in a terminal and tail the log to see progress:
  python3 run_voyager.py 2>&1 | tee voyager.log
"""
import os
import sys

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)


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

from voyager import Voyager

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 44869
MAX_ITERATIONS = int(sys.argv[2]) if len(sys.argv) > 2 else 160
RESUME = (sys.argv[3].lower() == "resume") if len(sys.argv) > 3 else False
MODEL_NAME = os.environ.get("VOYAGER_MODEL_NAME", "kimi-k2.6")

print("=" * 60)
print("VOYAGER LIFELONG LEARNING")
print("=" * 60)
print(f"Minecraft port: {PORT}")
print(f"API: opencode go ({MODEL_NAME})")
print(f"Max iterations: {MAX_ITERATIONS}")
print(f"Resume: {RESUME}")
print("=" * 60)
print("This will run continuously. Press Ctrl+C to stop.")
print("=" * 60)
print()

voyager = Voyager(
    mc_port=PORT,
    server_port=3000,
    openai_api_key=os.environ["OPENAI_API_KEY"],
    openai_api_base=os.environ["OPENAI_API_BASE"],
    action_agent_model_name=MODEL_NAME,
    curriculum_agent_model_name=MODEL_NAME,
    curriculum_agent_qa_model_name=MODEL_NAME,
    critic_agent_model_name=MODEL_NAME,
    skill_manager_model_name=MODEL_NAME,
    ckpt_dir="ckpt_voyager",
    resume=RESUME,
    max_iterations=MAX_ITERATIONS,
    env_wait_ticks=20,
    env_request_timeout=300,
    openai_api_request_timeout=240,
)

try:
    result = voyager.learn()
    print("\n" + "=" * 60)
    print("COMPLETE")
    print("=" * 60)
    print(f"Completed tasks: {result['completed_tasks']}")
    print(f"Failed tasks: {result['failed_tasks']}")
    print(f"Skills: {len(result['skills'])}")
except KeyboardInterrupt:
    print("\nInterrupted by user.")
finally:
    voyager.close()
    print("Voyager closed.")
