# Recording Agent Gameplay

This repo now supports several ways to visualize or record Voyager playing Minecraft.

## Replay Mod

- Source: Replay Mod docs and download page
- Best for: full client-side recordings, long sessions, camera editing after the run
- Recording behavior: once enabled in the client, Replay Mod records each world/server session and saves a `.mcpr` replay when you leave the world
- Video export: requires local `ffmpeg`

Install it with:

```bash
./venv/bin/python install_replaymod.py
```

By default this downloads `replaymod-1.19-2.6.26.jar` and installs it into `~/.minecraft/mods/`.

Replay Mod is a real Minecraft client mod. It does not attach directly to mineflayer.

## Prismarine Viewer Live Viewer

- Source: `prismarine-viewer` README and `examples/headless.js`
- Best for: live browser visualization of the mineflayer bot in first-person or third-person
- Benefit: no full player client is required just to watch the bot

This repo now wires the viewer through environment variables:

- `VOYAGER_VIEWER_PORT` enables the viewer web server
- `VOYAGER_VIEWER_FIRST_PERSON=1` switches to first-person
- `VOYAGER_VIEWER_DRAW_PATH=1` draws the recent path behind the bot
- `voyager/env/mineflayer/package.json` now includes `canvas`, which prismarine-viewer needs in this workspace

Example:

```bash
export VOYAGER_VIEWER_PORT=3007
export VOYAGER_VIEWER_DRAW_PATH=1
./venv/bin/python start_demo_server.py
./venv/bin/python run_recorded_demo.py 25565
```

Then open:

```text
http://127.0.0.1:3007/
```

To record the viewer page directly to MP4 in this environment:

```bash
./venv/bin/python capture_viewer.py http://127.0.0.1:3007/ recordings/voyager-demo.mp4 --duration 90
```

The default local server helper creates a small floating arena with logs and exposed stone so `run_recorded_demo.py` can execute a short deterministic task sequence without depending on a manually opened LAN world.

A generated sample recording is now stored at `recordings/voyager-demo.mp4`.

For a full one-command run that starts the local server, runs Voyager, records the viewer, crops the browser chrome, and stops everything automatically:

```bash
./venv/bin/python record_demo_pipeline.py
```

The default pipeline uses a longer task sequence than the earlier smoke test, runs in `direct` mode by default, records for up to 240 seconds, and overwrites `recordings/voyager-demo.mp4` with the cleaned result.

If the task run exits before the cap, capture stops automatically. If the task run is still active when capture hits the cap, the pipeline prints a warning so you can rerun it with a larger `--duration`.

`record_demo_pipeline.py` now also derives isolated default `--ckpt-dir` and `--server-root` paths from `--output`, so ad hoc smoke recordings do not trample each other's cached state unless you override those paths deliberately.

`direct` mode replays learned skill functions from `ckpt_voyager/skill/skills.json` directly. This is useful for recording because it preserves the real learned behavior while avoiding long idle gaps between action-model generations.

For random-seed worlds, switch the server to a natural overworld and disable the fixed arena:

```bash
./venv/bin/python record_demo_pipeline.py --world-type minecraft:normal --no-demo-arena --task-preset short-random --mode direct --fallback-to-agent --output recordings/random-world-demo.mp4
```

That path is intentionally shorter than the deterministic flat-world demo. It uses a minimal two-task survival chain as the current random-world baseline:

1. `Mine 1 wood log`
2. `Craft 1 crafting_table`

The recommended mode for this short chain is now `direct --fallback-to-agent`. In practice that keeps recordings visually active by replaying learned skills immediately, while still allowing the action agent to retry a task when direct replay cannot finish it cleanly.

There is also an exploratory longer preset:

1. `Mine 1 wood log`
2. `Craft 1 crafting_table`
3. `Mine 1 wood log`
4. `Craft 4 sticks`

There is now also a dedicated random-world wooden-pickaxe preset:

1. `Mine 1 wood log`
2. `Craft 1 crafting_table`
3. `Mine 1 wood log`
4. `Craft 4 sticks`
5. `Mine 1 wood log`
6. `Craft 1 wooden_pickaxe`

Current example:

```bash
./venv/bin/python record_demo_pipeline.py --world-type minecraft:normal --no-demo-arena --task-preset long-random --mode direct --fallback-to-agent --seed 12346 --max-attempts 3 --output recordings/random-world-long-demo.mp4
```

`record_demo_pipeline.py` now supports `--max-attempts` so random-world recordings can retry with a fresh world when spawn screening or early run setup fails. This avoids keeping a misleading partial recording from a failed first attempt.

For isolated local smoke runs, you can also override the default ports explicitly:

```bash
./venv/bin/python validate_random_world.py --task-preset short-random --mode direct --fallback-to-agent --seed 12345 --mc-port 25571 --bridge-port 3001
./venv/bin/python record_demo_pipeline.py --world-type minecraft:normal --no-demo-arena --task-preset short-random --mode direct --fallback-to-agent --mc-port 25573 --viewer-port 3008 --bridge-port 3003 --output recordings/random-world-demo-smoke.mp4
```

The repo now also ships a `Makefile` wrapper for the common random-world flows. The benchmark refresh targets default to a six-attempt fresh-world retry budget per seed so occasional spawn-screening misses do not invalidate an otherwise healthy run:

```bash
make benchmark-random-short
make benchmark-random-long
make validate-random-woodpick
make benchmark-random-world
make verify-random-world
make record-random-short-smoke
```

`capture_viewer.py` now also waits for non-black rendered frames on the Xvfb display before starting `ffmpeg`. That removes the old short-demo startup black screen that happened when the browser window existed but the prismarine viewer had not drawn yet.

To validate random-world capability without recording video:

```bash
./venv/bin/python validate_random_world.py --mode direct --fallback-to-agent --seed 12345
./venv/bin/python benchmark_random_world.py --task-preset short-random --mode direct --fallback-to-agent --seeds 12345 12346 12347 12348 12349 12350 12351 12352 12353 12354 12355 12356 12357 12358 12359 12360 12361 12362 12363 12364
./venv/bin/python benchmark_random_world.py --task-preset long-random --mode direct --fallback-to-agent --seeds 12345 12346 12347 12348 12349 12350 12351 12352 12353 12354
./venv/bin/python validate_random_world.py --task-preset woodpick-random --mode direct --fallback-to-agent --seed 12346
```

The current short-chain benchmark snapshot is written to `recordings/random-world-benchmark-20seeds-v2.json`. The latest rerun in this workspace succeeded on all sampled seeds `12345` through `12364` for the two-task baseline. Under the current `make benchmark-random-short` path, each seed gets up to 6 fresh-world attempts to smooth spawn-screening variance; the latest rerun landed at `average_attempt: 1.15` and `average_run_duration_seconds: 27.6285`. The older `recordings/random-world-benchmark.json` and `recordings/random-world-benchmark-6seeds.json` files have been retired.

The current long-chain benchmark snapshot is written to `recordings/random-world-long-benchmark-10seeds-v2.json`. The latest rerun succeeded on all sampled seeds `12345` through `12354` for the four-task `long-random` chain, with `average_attempt: 1.1` and `average_run_duration_seconds: 43.314`. The older `recordings/random-world-long-benchmark.json` file has been retired.

The current wooden-pickaxe validation snapshot is `recordings/random-world-woodpick-12346-v2.json`. It records the current successful seed-`12346` verification run for the six-task `woodpick-random` chain, with `duration_seconds: 68.73`. Exact fallback and observability values live in the JSON artifact.

By default, `benchmark_random_world.py` now keeps its per-seed JSON/log outputs under `recordings/_runs/<label-prefix>/`, while the checked-in top-level `*-v2.json` files remain the canonical published benchmark snapshots.

The validation JSON written by `validate_random_world.py` now carries run-level observability fields including `failed_task`, `failure_reason`, `failure_phase`, `used_fallback_on_tasks`, `fallback_events`, `task_outcomes`, `fallback_count`, `spawn_screening_required`, `spawn_screening_success`, `spawn_screening_attempts`, `spawn_screening_nearby_tree_initial`, and `duration_seconds`.

To recheck the current checked-in random-world artifacts in one command:

```bash
./venv/bin/python verify_random_world_artifacts.py
```

Docs hand-off note: use `make benchmark-random-world` followed by `make verify-random-world` as the canonical refresh sequence. Keep the published benchmark/validation snapshots in the top-level `recordings/*-v2.json` files, keep the checked-in demo videos as the canonical visual artifacts, and treat `recordings/_runs/` as transient per-seed run output that can be regenerated at any time.

## Prismarine Viewer Headless MP4

- Source: `prismarine-viewer/examples/headless.js`
- Best for: direct bot-view video rendering to a file
- Limitation: requires `ffmpeg` and `node-canvas-webgl`

The vendored `prismarine-viewer` dependency already contains the headless code path, but the current workspace does not yet include `node-canvas-webgl`. Once those dependencies are installed, this becomes a direct MP4 path.

## Browser Plus Virtual Display Capture

- Best for: recording the live viewer without `node-canvas-webgl`
- Method: run `Xvfb`, open the prismarine viewer in a Chromium-based browser inside that display, and capture the virtual display directly with `ffmpeg`

This is feasible in the current environment because it already has:

- a Chromium-based browser
- `Xvfb`
- `ffmpeg`

The current checked-in random-world recordings `recordings/random-world-demo.mp4` and `recordings/random-world-long-demo.mp4` were regenerated with this path and passed `ffmpeg -vf blackdetect` without reporting black segments.

## OS-Level Screen Recording

- OBS Studio
- `wf-recorder`
- desktop capture through `ffmpeg`

This is the most direct option for a local desktop session, but it depends on local GUI capture tools and is less repo-automatable than Replay Mod or prismarine viewer.

## Repo Visualization Outputs

Even without a video artifact, the repo now includes checkpoint-based visual outputs:

- `demo/index.html`
- `docs/index.html`
- `demo/dashboard.svg`
- `demo/tasks.svg`

These files are generated by `generate_demo.py` and let the real `ckpt_voyager` run be inspected locally and through GitHub Pages.
