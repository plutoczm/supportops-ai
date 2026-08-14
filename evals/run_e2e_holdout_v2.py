from __future__ import annotations

import json

from evals.e2e_holdout_v2 import build_e2e_holdout_v2_scenarios
from evals.e2e_sources import component_benchmark_texts, regression_v1_texts
from evals.e2e_suite import enforce_gates, evaluate_scenarios


def main() -> None:
    prohibited = [*component_benchmark_texts(), *regression_v1_texts()]
    metrics = evaluate_scenarios(
        build_e2e_holdout_v2_scenarios(),
        benchmark_version="supportops-e2e-holdout-v2",
        scope=(
            "fresh repository-held-out deterministic E2E scenarios created after the "
            "regression-v1 defect fix; not an external blind production benchmark"
        ),
        prohibited_texts=prohibited,
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    enforce_gates(metrics)


if __name__ == "__main__":
    main()
