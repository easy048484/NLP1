"""라우팅 골든셋 회귀 (실제 LLM, opt-in).

    pytest --live tests/test_routing_golden_live.py -q

evals/routing/golden.json 전체를 실제 파이프라인으로 돌려 정확도가 기준선
아래로 떨어지지 않는지 본다. 기본 `pytest -q` 에서는 deselect 된다
(conftest.py 의 live 마커 처리). 결과 파일은 evals/routing/results/ 에
`pytest` 라벨로 남는다.

기준선(_MIN_ACCURACY)은 evals/routing/README.md "기준선" 절의 baseline
결과에서 가져온다. spec.py/프롬프트를 고쳐 점수가 오르면 같이 올리세요.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.routing import run as routing_eval

_RESULTS = Path(routing_eval._RESULTS_DIR)
_MIN_ACCURACY = 0.85


@pytest.mark.live
def test_routing_golden_accuracy_does_not_regress():
    before = set(_RESULTS.glob("*_pytest_llm-auto.json"))
    assert routing_eval.main(["--label", "pytest"]) == 0
    created = set(_RESULTS.glob("*_pytest_llm-auto.json")) - before
    assert len(created) == 1
    report = json.loads(created.pop().read_text(encoding="utf-8"))

    summary = report["summary"]
    assert summary["errors"] == 0, summary
    assert summary["accuracy"] >= _MIN_ACCURACY, summary["confusion"]
