"""라우팅 골든셋 채점기 (담당: 정민).

golden.json 의 시나리오를 실제 파이프라인(orchestrator.router.route)에 한 턴씩
흘려보내고, 실행된 에이전트 집합을 정답과 비교해 점수를 낸다. 결과는 답변
본문까지 포함해 results/ 아래에 JSON + Markdown 으로 남긴다 — 지원의 답변 품질
채점(코드 규칙 검사 + AI 심사)이 이 파일을 입력으로 쓴다.

실행 (apps/api 에서):

    python -m evals.routing.run                    # LLM 라우팅 (루트 .env 의 키 사용)
    python -m evals.routing.run --llm off          # 키워드 규칙 라우팅만 (비교용)
    python -m evals.routing.run --only flow-demo-A,single-tax-01
    python -m evals.routing.run --tag hijack:asset
    python -m evals.routing.run --label baseline   # 파일 이름에 라벨을 붙인다

채점 규칙 (턴 단위)
-----------------
- exact      실행된 에이전트 집합 == expected (또는 also_ok 중 하나). 순서 무관.
- forbid     forbid 에 있는 에이전트가 하나라도 실행되면 실패.
- pass       exact and not forbid.  ← 기준 점수 (정확도 = pass 턴 / 전체 턴)
- covered    expected 가 전부 실행됐는지 (다른 에이전트가 더 붙어도 인정하는
             느슨한 지표. "정답이 빠진 것"과 "덤이 붙은 것"을 구분하려고 둔다)

세션은 시나리오마다 새로 시작하고(InMemorySessionStore), 같은 시나리오 안의
턴은 같은 session_id 로 이어진다 — 이어가기/하이재킹/전환 판단이 실제 이력을
보고 이뤄지게 하기 위해서다. DB 는 쓰지 않는다.

라우팅 LLM 의 판단 근거(reason)는 llm.claude.extract 를 감싸서 잡아낸다 —
planner 코드는 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_API_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _API_DIR.parents[1]
_GOLDEN_PATH = Path(__file__).resolve().parent / "golden.json"
_RESULTS_DIR = Path(__file__).resolve().parent / "results"

if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))


def _load_env() -> None:
    """main.py 와 같은 위치의 .env 를 읽는다. DATABASE_URL 은 무시한다(세션은
    인메모리, family_graph 조회는 DB 없이 None 으로 폴백)."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    env_path = _REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    os.environ.pop("DATABASE_URL", None)


# 라우팅 LLM 판단 캡처


class _RouteCapture:
    """claude.extract 를 감싸 route_message 도구 호출 결과만 기록한다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []
        self._original = None

    def install(self) -> None:
        from llm import claude
        from orchestrator import planner

        self._original = claude.extract
        tool_name = planner._ROUTE_TOOL_NAME
        capture = self

        def wrapped(**kwargs):
            result = capture._original(**kwargs)
            if kwargs.get("tool", {}).get("name") == tool_name:
                with capture._lock:
                    capture.calls.append(
                        {
                            "agents": list(result.get("agents", [])),
                            "reason": result.get("reason", ""),
                        }
                    )
            return result

        claude.extract = wrapped

    def drain(self) -> list[dict[str, Any]]:
        with self._lock:
            calls, self.calls = self.calls, []
        return calls


# 채점


def _score_turn(turn: dict[str, Any], actual: list[str]) -> dict[str, Any]:
    actual_set = set(actual)
    expected = set(turn["expected"])
    ok_sets = [expected] + [set(x) for x in turn.get("also_ok", [])]
    forbid = set(turn.get("forbid", []))
    exact = actual_set in ok_sets
    forbid_hit = sorted(actual_set & forbid)
    return {
        "exact": exact,
        "covered": expected <= actual_set,
        "forbid_hit": forbid_hit,
        "pass": exact and not forbid_hit,
        "matched_set": (
            sorted(next(s for s in ok_sets if s == actual_set)) if exact else None
        ),
    }


def _run_turn(
    session_id: str,
    axis: Optional[str],
    turn: dict[str, Any],
    capture: _RouteCapture,
) -> dict[str, Any]:
    from orchestrator import registry, router
    from schemas import AgentInput

    keyword_hits = [n.value for n in registry.match_keywords(turn["message"])]
    capture.drain()
    started = time.perf_counter()
    record: dict[str, Any] = {
        "message": turn["message"],
        "expected": turn["expected"],
        "also_ok": turn.get("also_ok", []),
        "forbid": turn.get("forbid", []),
        "tags": turn.get("tags", []),
        "keyword_hits": keyword_hits,
    }
    try:
        response = router.route(
            AgentInput(session_id=session_id, user_message=turn["message"], axis=axis)
        )
    except Exception as exc:  # noqa: BLE001 — 한 턴 실패가 전체 채점을 막지 않게
        record.update(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "actual": [],
                "path": None,
                "elapsed_sec": round(time.perf_counter() - started, 2),
                "llm_route": capture.drain(),
                "score": _score_turn(turn, []),
            }
        )
        return record

    actual = [a.value for a in response.agents]
    record.update(
        {
            "actual": actual,
            "primary": response.agent.value,
            "path": response.path,
            "next_action": response.next_action,
            "verification": (
                response.verification.model_dump() if response.verification else None
            ),
            "elapsed_sec": round(time.perf_counter() - started, 2),
            "llm_route": capture.drain(),
            "reply": response.reply,
            "contributions": [
                {
                    "agent": c.agent.value,
                    "reply": c.reply,
                    "next_action": c.next_action,
                    "handoffs": [h.target.value for h in c.handoffs],
                }
                for c in response.contributions
            ],
            "financial_profile": (
                response.financial_profile.model_dump(exclude_none=True)
                if response.financial_profile
                else None
            ),
            "will_status": (
                response.will_status.model_dump() if response.will_status else None
            ),
            "data": response.data,
            "score": _score_turn(turn, actual),
        }
    )
    return record


def _summarize(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    turns = [t for s in scenarios for t in s["turns"]]
    total = len(turns)
    passed = sum(1 for t in turns if t["score"]["pass"])
    exact = sum(1 for t in turns if t["score"]["exact"])
    covered = sum(1 for t in turns if t["score"]["covered"])
    errors = sum(1 for t in turns if t.get("error"))
    llm_routed = sum(1 for t in turns if t["llm_route"])

    by_tag: dict[str, Counter] = defaultdict(Counter)
    for t in turns:
        for tag in t["tags"]:
            by_tag[tag]["total"] += 1
            by_tag[tag]["pass"] += int(t["score"]["pass"])

    # 에이전트별 precision/recall — 턴마다 expected 집합 vs actual 집합.
    per_agent: dict[str, Counter] = defaultdict(Counter)
    for t in turns:
        exp, act = set(t["expected"]), set(t["actual"])
        for a in exp | act:
            per_agent[a]["tp"] += int(a in exp and a in act)
            per_agent[a]["fp"] += int(a not in exp and a in act)
            per_agent[a]["fn"] += int(a in exp and a not in act)

    # 오답만 따로: 어디로 샜는지.
    confusion: Counter = Counter()
    for t in turns:
        if not t["score"]["pass"]:
            confusion[(",".join(sorted(t["expected"])), ",".join(t["actual"]))] += 1

    def _rate(n: int, d: int) -> Optional[float]:
        return round(n / d, 4) if d else None

    return {
        "turns": total,
        "pass": passed,
        "accuracy": _rate(passed, total),
        "exact": exact,
        "covered": covered,
        "covered_rate": _rate(covered, total),
        "errors": errors,
        "llm_routed_turns": llm_routed,
        "by_scenario": [
            {
                "id": s["id"],
                "pass": sum(1 for t in s["turns"] if t["score"]["pass"]),
                "turns": len(s["turns"]),
            }
            for s in scenarios
        ],
        "by_tag": {
            tag: {
                "pass": c["pass"],
                "total": c["total"],
                "rate": _rate(c["pass"], c["total"]),
            }
            for tag, c in sorted(by_tag.items())
        },
        "per_agent": {
            a: {
                "tp": c["tp"],
                "fp": c["fp"],
                "fn": c["fn"],
                "precision": _rate(c["tp"], c["tp"] + c["fp"]),
                "recall": _rate(c["tp"], c["tp"] + c["fn"]),
            }
            for a, c in sorted(per_agent.items())
        },
        "confusion": [
            {"expected": e, "actual": a, "count": n}
            for (e, a), n in confusion.most_common()
        ],
    }


# 보고서


def _pct(rate: Optional[float]) -> str:
    return "-" if rate is None else f"{rate * 100:.1f}%"


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _render_markdown(report: dict[str, Any]) -> str:
    meta, summary = report["meta"], report["summary"]
    out: list[str] = []
    out.append("# 라우팅 채점 결과")
    out.append("")
    out.append(f"- 실행 시각: {meta['run_at']}")
    out.append(f"- 커밋: `{meta['git_sha']}` ({meta['git_branch']})")
    out.append(
        f"- 라우팅 모드: `ORCHESTRATOR_USE_LLM={meta['llm_mode']}`"
        f" / 모델: `{meta['model']}` / 라우터 모델: `{meta['router_model'] or '(=모델)'}`"
    )
    out.append(f"- 골든셋: `{meta['golden_version']}` ({meta['golden_path']})")
    if meta.get("filter"):
        out.append(f"- 필터: {meta['filter']}")
    out.append("")
    out.append("## 요약")
    out.append("")
    out.append("| 지표 | 값 |")
    out.append("|---|---|")
    out.append(
        f"| **정확도 (pass / 전체 턴)** | **{summary['pass']} / {summary['turns']}"
        f" = {_pct(summary['accuracy'])}** |"
    )
    out.append(f"| 정답 집합 일치(exact) | {summary['exact']} |")
    out.append(
        f"| 정답 포함(covered, 덤 허용) | {summary['covered']}"
        f" ({_pct(summary['covered_rate'])}) |"
    )
    out.append(f"| LLM 라우팅이 실제로 쓰인 턴 | {summary['llm_routed_turns']} |")
    out.append(f"| 실행 오류 턴 | {summary['errors']} |")
    out.append("")
    out.append("### 에이전트별")
    out.append("")
    out.append("| 에이전트 | TP | FP | FN | precision | recall |")
    out.append("|---|---|---|---|---|---|")
    for a, c in summary["per_agent"].items():
        out.append(
            f"| {a} | {c['tp']} | {c['fp']} | {c['fn']} |"
            f" {_pct(c['precision'])} | {_pct(c['recall'])} |"
        )
    out.append("")
    out.append("### 태그별")
    out.append("")
    out.append("| 태그 | pass / total | rate |")
    out.append("|---|---|---|")
    for tag, c in summary["by_tag"].items():
        out.append(f"| {tag} | {c['pass']} / {c['total']} | {_pct(c['rate'])} |")
    out.append("")
    if summary["confusion"]:
        out.append("### 오답 (expected → actual)")
        out.append("")
        out.append("| expected | actual | 건수 |")
        out.append("|---|---|---|")
        for row in summary["confusion"]:
            out.append(
                f"| {row['expected']} | {row['actual'] or '(없음)'} | {row['count']} |"
            )
        out.append("")

    out.append("## 턴별 결과")
    out.append("")
    out.append(
        "| 시나리오 | # | 판정 | 발화 | expected | actual | path | 키워드 힌트 | LLM 근거 |"
    )
    out.append("|---|---|---|---|---|---|---|---|---|")
    for s in report["scenarios"]:
        for i, t in enumerate(s["turns"], 1):
            mark = "✅" if t["score"]["pass"] else "❌"
            if t.get("error"):
                mark = "💥"
            reason = "; ".join(
                f"{'+'.join(r['agents'])}: {r['reason']}" for r in t["llm_route"]
            )
            out.append(
                f"| {s['id']} | {i} | {mark} | {_md_escape(t['message'])} |"
                f" {'+'.join(t['expected'])} | {'+'.join(t['actual']) or '(없음)'} |"
                f" {t.get('path') or '-'} | {','.join(t['keyword_hits']) or '-'} |"
                f" {_md_escape(reason) or '-'} |"
            )
    out.append("")

    out.append("## 답변 본문")
    out.append("")
    out.append("답변 품질 채점용. 시나리오 순서 = 한 세션의 대화 순서다.")
    out.append("")
    for s in report["scenarios"]:
        out.append(f"### {s['id']} — {s['title']} (axis={s['axis'] or '-'})")
        out.append("")
        for i, t in enumerate(s["turns"], 1):
            mark = "✅" if t["score"]["pass"] else "❌"
            out.append(f"#### 턴 {i} {mark}")
            out.append("")
            out.append(f"**사용자:** {t['message']}")
            out.append("")
            if t.get("error"):
                out.append(f"**오류:** `{t['error']}`")
                out.append("")
                continue
            out.append(
                f"**실행:** {' + '.join(t['actual'])} (path={t['path']},"
                f" next_action={t.get('next_action') or '-'}, {t['elapsed_sec']}s)"
            )
            out.append("")
            out.append("**답변:**")
            out.append("")
            out.append("```text")
            out.append(t["reply"])
            out.append("```")
            out.append("")
    return "\n".join(out)


# 실행


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=_REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--llm",
        choices=["auto", "on", "off", "required"],
        default="auto",
        help="ORCHESTRATOR_USE_LLM 값. off 면 키워드 규칙 라우팅만 (기본 auto)",
    )
    parser.add_argument("--only", help="시나리오 id 쉼표 목록")
    parser.add_argument(
        "--tag", help="이 태그가 붙은 턴만 채점 (앞 턴은 이력용으로 실행)"
    )
    parser.add_argument("--label", default="run", help="결과 파일 이름 라벨")
    parser.add_argument("--out", default=str(_RESULTS_DIR), help="결과 저장 폴더")
    parser.add_argument("--golden", default=str(_GOLDEN_PATH))
    parser.add_argument("--list", action="store_true", help="시나리오 목록만 출력")
    args = parser.parse_args(argv)
    # Windows 콘솔(cp949)에서 한글·기호 출력이 깨지지 않게.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    scenarios = golden["scenarios"]
    if args.list:
        for s in scenarios:
            print(f"{s['id']:32s} {len(s['turns'])}턴  {s['title']}")
        return 0

    _load_env()
    os.environ["ORCHESTRATOR_USE_LLM"] = args.llm

    from orchestrator import llm_policy, router
    from orchestrator.session_store import InMemorySessionStore

    router.default_store = InMemorySessionStore()
    capture = _RouteCapture()
    capture.install()

    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        scenarios = [s for s in scenarios if s["id"] in wanted]

    run_at = datetime.now().astimezone()
    print(
        f"[routing-eval] {len(scenarios)} 시나리오 / "
        f"{sum(len(s['turns']) for s in scenarios)} 턴, llm={llm_policy.llm_status()}"
    )

    results: list[dict[str, Any]] = []
    for s in scenarios:
        session_id = f"eval-{run_at.strftime('%Y%m%d%H%M%S')}-{s['id']}"
        turn_records: list[dict[str, Any]] = []
        print(f"\n== {s['id']} — {s['title']}")
        for i, turn in enumerate(s["turns"], 1):
            rec = _run_turn(session_id, s.get("axis"), turn, capture)
            if args.tag and args.tag not in turn.get("tags", []):
                rec["score"]["skipped"] = True
            turn_records.append(rec)
            mark = "PASS" if rec["score"]["pass"] else "FAIL"
            if rec.get("error"):
                mark = "ERR "
            print(
                f"  [{mark}] {i}. {turn['message'][:40]!r} → "
                f"{'+'.join(rec['actual']) or '(없음)'}  "
                f"(expected {'+'.join(turn['expected'])}, {rec['elapsed_sec']}s)"
            )
        if args.tag:
            turn_records = [
                t for t in turn_records if not t["score"].get("skipped", False)
            ]
        results.append(
            {
                "id": s["id"],
                "title": s["title"],
                "axis": s.get("axis"),
                "session_id": session_id,
                "turns": turn_records,
            }
        )

    summary = _summarize(results)
    report = {
        "meta": {
            "run_at": run_at.isoformat(timespec="seconds"),
            "git_sha": _git("rev-parse", "--short", "HEAD"),
            "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "llm_mode": args.llm,
            "llm_status": llm_policy.llm_status(),
            "model": os.getenv("CLAUDE_MODEL", "") or "(default)",
            "router_model": llm_policy.router_model(),
            "golden_version": golden.get("version"),
            "golden_path": str(Path(args.golden).relative_to(_API_DIR)),
            "filter": " ".join(
                x
                for x in [
                    f"--only {args.only}" if args.only else "",
                    f"--tag {args.tag}" if args.tag else "",
                ]
                if x
            ),
            "label": args.label,
        },
        "summary": summary,
        "scenarios": results,
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = (
        f"{run_at.strftime('%Y%m%d-%H%M')}_{report['meta']['git_sha']}"
        f"_{args.label}_llm-{args.llm}"
    )
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(_render_markdown(report), encoding="utf-8")

    print(
        f"\n정확도 {summary['pass']}/{summary['turns']} = {_pct(summary['accuracy'])}"
        f"  (covered {_pct(summary['covered_rate'])}, 오류 {summary['errors']})"
    )
    print(f"결과: {md_path}\n      {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
