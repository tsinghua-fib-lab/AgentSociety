"""Compare installed SDKs in fresh, alternately ordered Python processes."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

SCENARIOS = {
    "sdk": "import agentsociety2",
    "hook_context": "from agentsociety2.agent.base.skill_hook_context import HookContext",
    "person_agent": "from agentsociety2 import PersonAgent",
}


def sample(python: Path, statement: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="as2-import-bench-") as workdir:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("AGENTSOCIETY_") and k != "PYTHONPATH"
        }
        env.update(
            AGENTSOCIETY_LLM_API_KEY="benchmark-unused",
            AGENTSOCIETY_LLM_API_BASE="https://example.invalid/v1",
            AGENTSOCIETY_HOME_DIR=workdir,
            MEM0_TELEMETRY="False",
            ANONYMIZED_TELEMETRY="False",
            LITELLM_LOCAL_MODEL_COST_MAP="True",
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
        )
        code = (
            "import time, sys, json, resource\n"
            "start = time.perf_counter()\n"
            f"{statement}\n"
            "elapsed = time.perf_counter() - start\n"
            "import agentsociety2\n"
            "print('BENCHMARK_JSON=' + json.dumps({"
            "'import_seconds': elapsed,"
            "'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"
            "'sdk_file': agentsociety2.__file__,"
            "'python': sys.version,"
            "'heavy_modules': [n for n in ('litellm', 'ray', 'agentsociety2.config') if n in sys.modules]"
            "}))\n"
        )
        start = time.perf_counter()
        completed = subprocess.run(
            [str(python), "-c", code],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        wall = time.perf_counter() - start
        payload = next(
            line.removeprefix("BENCHMARK_JSON=")
            for line in completed.stdout.splitlines()
            if line.startswith("BENCHMARK_JSON=")
        )
        row = json.loads(payload)
        row["process_seconds"] = wall
        return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-python", type=Path, required=True)
    parser.add_argument("--after-python", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("--repeats must be at least 2")
    interpreters = {
        "before": args.before_python.absolute(),
        "after": args.after_python.absolute(),
    }
    results = {
        scenario: {variant: [] for variant in interpreters} for scenario in SCENARIOS
    }
    for scenario, statement in SCENARIOS.items():
        for repeat in range(args.repeats):
            order = ("before", "after") if repeat % 2 == 0 else ("after", "before")
            for variant in order:
                row = sample(interpreters[variant], statement)
                results[scenario][variant].append(row)
                print(
                    json.dumps(
                        {
                            "scenario": scenario,
                            "variant": variant,
                            "repeat": repeat + 1,
                            **row,
                        }
                    ),
                    flush=True,
                )
    summaries = {}
    for scenario, variants in results.items():
        summaries[scenario] = {}
        for variant, rows in variants.items():
            summaries[scenario][variant] = {
                metric: {
                    "median": statistics.median(row[metric] for row in rows),
                    "min": min(row[metric] for row in rows),
                    "max": max(row[metric] for row in rows),
                }
                for metric in ("import_seconds", "process_seconds", "max_rss_kib")
            }
    args.output.write_text(
        json.dumps(
            {
                "method": "Fresh interpreters, alternating before/after order, warm filesystem cache, no LLM calls; Linux peak RSS in KiB",
                "repeats": args.repeats,
                "samples": results,
                "summary": summaries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
