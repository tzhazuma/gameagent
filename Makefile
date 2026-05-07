.NOTPARALLEL:

PYTHON ?= ./venv/bin/python

SHORT_RANDOM_SEEDS := \
	12345 12346 12347 12348 12349 12350 12351 12352 12353 12354 \
	12355 12356 12357 12358 12359 12360 12361 12362 12363 12364
LONG_RANDOM_SEEDS := 12345 12346 12347 12348 12349 12350 12351 12352 12353 12354
WOODPICK_SEED ?= 12346

SHORT_BENCH_OUTPUT ?= recordings/random-world-benchmark-20seeds-v2.json
SHORT_BENCH_ARTIFACTS ?= recordings/_runs/random-world-benchmark-20seeds-v2
SHORT_BENCH_MAX_ATTEMPTS ?= 6
SHORT_BENCH_MC_PORT ?= 25565
SHORT_BENCH_BRIDGE_PORT ?= 3000

LONG_BENCH_OUTPUT ?= recordings/random-world-long-benchmark-10seeds-v2.json
LONG_BENCH_ARTIFACTS ?= recordings/_runs/random-world-long-benchmark-10seeds-v2
LONG_BENCH_MAX_ATTEMPTS ?= 6
LONG_BENCH_MC_PORT ?= 25566
LONG_BENCH_BRIDGE_PORT ?= 3001

WOODPICK_OUTPUT ?= recordings/random-world-woodpick-$(WOODPICK_SEED)-v2.json
WOODPICK_ARTIFACTS ?= recordings/_runs/random-world-woodpick-$(WOODPICK_SEED)-v2
WOODPICK_MAX_ATTEMPTS ?= 6
WOODPICK_MC_PORT ?= 25567
WOODPICK_BRIDGE_PORT ?= 3002

SHORT_SMOKE_OUTPUT ?= recordings/random-world-demo-smoke.mp4
SHORT_SMOKE_MC_PORT ?= 25573
SHORT_SMOKE_VIEWER_PORT ?= 3008
SHORT_SMOKE_BRIDGE_PORT ?= 3003

.PHONY: test verify-random-world validate-random-short validate-random-woodpick benchmark-random-short benchmark-random-long benchmark-random-world refresh-random-world record-random-short-smoke

test:
	python -m unittest discover -s tests -p "test_*.py"

verify-random-world:
	$(PYTHON) verify_random_world_artifacts.py

validate-random-short:
	$(PYTHON) validate_random_world.py \
		--task-preset short-random \
		--mode direct \
		--fallback-to-agent \
		--seed 12345 \
		--max-attempts $(SHORT_BENCH_MAX_ATTEMPTS) \
		--mc-port $(SHORT_BENCH_MC_PORT) \
		--bridge-port $(SHORT_BENCH_BRIDGE_PORT)

validate-random-woodpick:
	$(PYTHON) validate_random_world.py \
		--task-preset woodpick-random \
		--mode direct \
		--fallback-to-agent \
		--seed $(WOODPICK_SEED) \
		--label random-world-woodpick-$(WOODPICK_SEED)-v2 \
		--max-attempts $(WOODPICK_MAX_ATTEMPTS) \
		--mc-port $(WOODPICK_MC_PORT) \
		--bridge-port $(WOODPICK_BRIDGE_PORT) \
		--artifacts-dir $(WOODPICK_ARTIFACTS) \
		--output-json $(WOODPICK_OUTPUT)

benchmark-random-short:
	$(PYTHON) benchmark_random_world.py \
		--task-preset short-random \
		--mode direct \
		--fallback-to-agent \
		--seeds $(SHORT_RANDOM_SEEDS) \
		--max-attempts $(SHORT_BENCH_MAX_ATTEMPTS) \
		--mc-port $(SHORT_BENCH_MC_PORT) \
		--bridge-port $(SHORT_BENCH_BRIDGE_PORT) \
		--artifacts-dir $(SHORT_BENCH_ARTIFACTS) \
		--output-json $(SHORT_BENCH_OUTPUT)

benchmark-random-long:
	$(PYTHON) benchmark_random_world.py \
		--task-preset long-random \
		--mode direct \
		--fallback-to-agent \
		--seeds $(LONG_RANDOM_SEEDS) \
		--max-attempts $(LONG_BENCH_MAX_ATTEMPTS) \
		--mc-port $(LONG_BENCH_MC_PORT) \
		--bridge-port $(LONG_BENCH_BRIDGE_PORT) \
		--artifacts-dir $(LONG_BENCH_ARTIFACTS) \
		--output-json $(LONG_BENCH_OUTPUT)

benchmark-random-world:
	$(MAKE) benchmark-random-short
	$(MAKE) benchmark-random-long
	$(MAKE) validate-random-woodpick

refresh-random-world:
	$(MAKE) benchmark-random-world
	$(MAKE) verify-random-world

record-random-short-smoke:
	$(PYTHON) record_demo_pipeline.py \
		--world-type minecraft:normal \
		--no-demo-arena \
		--task-preset short-random \
		--mode direct \
		--fallback-to-agent \
		--mc-port $(SHORT_SMOKE_MC_PORT) \
		--viewer-port $(SHORT_SMOKE_VIEWER_PORT) \
		--bridge-port $(SHORT_SMOKE_BRIDGE_PORT) \
		--output $(SHORT_SMOKE_OUTPUT)
