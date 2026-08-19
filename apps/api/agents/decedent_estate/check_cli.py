"""
유언장 텍스트를 넣으면 requirement_checker 결과를 사람이 읽기 좋은 형태로 보여주는
실행 스크립트.

사용법:
    python agents/decedent_estate/check_cli.py path/to/will.txt
    python agents/decedent_estate/check_cli.py path/to/will.txt --handwriting yes --seal seal_or_fingerprint
    cat will.txt | python agents/decedent_estate/check_cli.py   # 표준입력

apps/api 디렉터리 밖에서 실행해도 되도록, 이 파일 기준으로 apps/api 루트를
sys.path 에 추가한 뒤 절대 import 를 사용한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[2]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from agents.decedent_estate.requirement_checker import (  # noqa: E402
    RequirementResult,
    check_requirements,
)

_GRADE_ICON = {
    "GREEN": "🟢",
    "YELLOW": "🟡",
    "RED": "🔴",
    "WHITE": "⚪",
    "PENDING": "❓",
}
_ORDER = ["date", "address", "name", "handwriting", "seal", "interseal"]


def format_results(results: dict[str, RequirementResult]) -> str:
    lines: list[str] = []
    for req_id in _ORDER:
        r = results[req_id]
        icon = _GRADE_ICON.get(r.grade or "", "·")
        cond = r.condition_id or "(미확인)"
        precedents = ", ".join(r.precedent_ids) if r.precedent_ids else "-"
        lines.append(
            f"{icon} {r.name:<8} grade={r.grade or '-':<8} condition={cond:<20} precedents={precedents}"
        )
        if r.extracted:
            lines.append(f"    extracted: {r.extracted}")
    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="유언장 텍스트 요건 판정 결과 확인")
    parser.add_argument(
        "file", nargs="?", help="유언장 텍스트 파일 경로 (생략 시 표준입력)"
    )
    parser.add_argument(
        "--handwriting",
        choices=["yes", "no_or_partial_typed"],
        default=None,
        help="전문 자서 여부 사용자 확인 답변 (생략 시 미확인=PENDING)",
    )
    parser.add_argument(
        "--seal",
        choices=["seal_or_fingerprint", "signature_only", "absent"],
        default=None,
        help="날인 여부 사용자 확인 답변 (생략 시 미확인=PENDING)",
    )
    args = parser.parse_args()

    text = (
        Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    )

    results = check_requirements(
        text, handwriting_answer=args.handwriting, seal_answer=args.seal
    )
    print(format_results(results))


if __name__ == "__main__":
    main()
