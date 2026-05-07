import unittest
from pathlib import Path

from benchmark_random_world import resolve_benchmark_layout, summarize_results
from capture_viewer import is_rendered_viewer_ready
from record_demo_pipeline import resolve_recording_layout, resolve_requested_tasks, uses_random_world_server
from validate_random_world import classify_failure_phase, resolve_validation_layout, summarize_metrics


class ValidateRandomWorldTests(unittest.TestCase):
    def test_classify_failure_phase_distinguishes_repeated_mine_log_steps(self) -> None:
        tasks = [
            "Mine 1 wood log",
            "Craft 1 crafting_table",
            "Mine 1 wood log",
            "Craft 4 sticks",
            "Mine 1 wood log",
        ]

        self.assertEqual(
            classify_failure_phase(tasks, tasks[:2], ["Mine 1 wood log"], None),
            "mine_log_second",
        )
        self.assertEqual(
            classify_failure_phase(tasks, tasks[:4], ["Mine 1 wood log"], None),
            "mine_log_third",
        )

    def test_classify_failure_phase_detects_spawn_and_completion(self) -> None:
        tasks = ["Mine 1 wood log", "Craft 1 crafting_table"]

        self.assertEqual(classify_failure_phase(tasks, [], [], "spawn_screening_failed"), "spawn")
        self.assertEqual(classify_failure_phase(tasks, tasks, [], None), "completed")
        self.assertEqual(classify_failure_phase(tasks, [], [tasks[0]], "server_ready_timeout"), "server")

    def test_summarize_metrics_preserves_failure_reason_and_counts(self) -> None:
        tasks = [
            "Mine 1 wood log",
            "Craft 1 crafting_table",
            "Mine 1 wood log",
            "Craft 4 sticks",
        ]
        result = {
            "completed": tasks[:3],
            "failed": ["Craft 4 sticks"],
            "error": "craft_failed",
            "fallback_count": "2",
            "spawn_screening_required": 1,
            "spawn_screening_success": 0,
            "spawn_screening_attempts": "3",
            "spawn_screening_nearby_tree_initial": 1,
            "duration_seconds": 12,
            "task_outcomes": [{"task": tasks[0], "success": True}],
        }

        summary = summarize_metrics(result, tasks)

        self.assertEqual(summary["failed_task"], "Craft 4 sticks")
        self.assertEqual(summary["failure_reason"], "craft_failed")
        self.assertEqual(summary["failure_phase"], "craft_sticks")
        self.assertEqual(summary["fallback_count"], 2)
        self.assertTrue(summary["spawn_screening_required"])
        self.assertFalse(summary["spawn_screening_success"])
        self.assertEqual(summary["spawn_screening_attempts"], 3)
        self.assertTrue(summary["spawn_screening_nearby_tree_initial"])
        self.assertEqual(summary["duration_seconds"], 12.0)


class RecordingLayoutTests(unittest.TestCase):
    def test_resolve_requested_tasks_uses_shared_random_world_presets(self) -> None:
        self.assertEqual(
            resolve_requested_tasks(["placeholder"], "short-random"),
            ["Mine 1 wood log", "Craft 1 crafting_table"],
        )
        self.assertEqual(resolve_requested_tasks(["keep"], "default"), ["keep"])

    def test_uses_random_world_server_only_for_normal_world_random_runs(self) -> None:
        self.assertTrue(uses_random_world_server("minecraft:normal", False, None))
        self.assertTrue(uses_random_world_server("minecraft:normal", True, "short-random"))
        self.assertFalse(uses_random_world_server("minecraft:flat", False, "short-random"))
        self.assertFalse(uses_random_world_server("minecraft:normal", True, None))

    def test_resolve_recording_layout_derives_isolated_paths_from_output(self) -> None:
        root = Path("/tmp/voyager")
        output_path, ckpt_path, server_root, ready_file = resolve_recording_layout(
            root,
            output="recordings/random-world-demo.mp4",
            ckpt_dir=None,
            server_root=None,
            world_type="minecraft:normal",
            demo_arena=False,
            task_preset="short-random",
        )

        self.assertEqual(output_path, root / "recordings/random-world-demo.mp4")
        self.assertEqual(ckpt_path, root / "ckpt_recordings_random_world_demo")
        self.assertEqual(server_root, root / ".demo_server_random_recordings_random_world_demo")
        self.assertEqual(ready_file, server_root / "ready.json")


class ValidationAndBenchmarkLayoutTests(unittest.TestCase):
    def test_resolve_validation_layout_derives_artifacts_and_server_paths(self) -> None:
        root = Path("/tmp/voyager")
        artifacts_root, ckpt_path, server_root, done_file, ready_file = resolve_validation_layout(
            root,
            label="random-world-12345",
            artifacts_dir="recordings/_runs/random-world",
            ckpt_dir=None,
            server_root=None,
        )

        self.assertEqual(artifacts_root, root / "recordings/_runs/random-world")
        self.assertEqual(ckpt_path, root / "ckpt_random_world_12345")
        self.assertEqual(server_root, root / ".demo_server_random_world_12345")
        self.assertEqual(done_file, artifacts_root / "random-world-12345.done")
        self.assertEqual(ready_file, server_root / "ready.json")

    def test_resolve_benchmark_layout_uses_canonical_paths(self) -> None:
        root = Path("/tmp/voyager")
        label_prefix, output_path, artifacts_root, ckpt_path, server_root = resolve_benchmark_layout(
            root,
            task_preset="short-random",
            label_prefix=None,
            output_json=None,
            artifacts_dir=None,
            ckpt_dir=None,
            server_root=None,
        )

        self.assertEqual(label_prefix, "random-world")
        self.assertEqual(output_path, root / "recordings/random-world-benchmark.json")
        self.assertEqual(artifacts_root, root / "recordings/_runs/random-world")
        self.assertEqual(ckpt_path, root / "ckpt_random_world_benchmark")
        self.assertEqual(server_root, root / ".demo_server_random_world_benchmark")

    def test_summarize_results_aggregates_success_duration_and_failures(self) -> None:
        results = [
            {
                "seed": "12345",
                "result": {
                    "success": True,
                    "failure_phase": "completed",
                    "fallback_count": 0,
                    "duration_seconds": 10.0,
                    "attempt": 1,
                },
            },
            {
                "seed": "12346",
                "result": {
                    "success": False,
                    "failed_task": "Craft 4 sticks",
                    "failure_phase": "craft_sticks",
                    "fallback_count": 1,
                    "duration_seconds": 20.0,
                    "attempt": 2,
                },
            },
        ]

        summary = summarize_results(
            results,
            task_preset="long-random",
            mode="direct",
            fallback_to_agent=True,
            seed_count=2,
            duration_seconds=45.678,
        )

        self.assertEqual(summary["task_preset"], "long-random")
        self.assertEqual(summary["mode"], "direct")
        self.assertTrue(summary["fallback_to_agent"])
        self.assertEqual(summary["success_count"], 1)
        self.assertEqual(summary["success_rate"], 0.5)
        self.assertEqual(summary["duration_seconds"], 45.68)
        self.assertEqual(summary["total_fallback_count"], 1)
        self.assertEqual(summary["average_fallback_count"], 0.5)
        self.assertEqual(summary["average_attempt"], 1.5)
        self.assertEqual(summary["average_run_duration_seconds"], 15.0)
        self.assertEqual(summary["failure_phase_counts"], {"completed": 1, "craft_sticks": 1})
        self.assertEqual(summary["failed_task_counts"], {"Craft 4 sticks": 1})


class CaptureViewerTests(unittest.TestCase):
    def test_is_rendered_viewer_ready_requires_non_black_metrics(self) -> None:
        self.assertFalse(is_rendered_viewer_ready(None, black_threshold=98, min_stddev=8))
        self.assertFalse(is_rendered_viewer_ready((98.0, 9.0), black_threshold=98, min_stddev=8))
        self.assertFalse(is_rendered_viewer_ready((50.0, 7.99), black_threshold=98, min_stddev=8))
        self.assertTrue(is_rendered_viewer_ready((50.0, 8.0), black_threshold=98, min_stddev=8))


if __name__ == "__main__":
    unittest.main()
