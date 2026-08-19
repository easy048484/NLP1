"""
LLM API로 보내기 전 부분 마스킹 (CLAUDE.md 절대 원칙 4).

성명·주소·날짜는 요건 판정에 필요하므로 그대로 둔다. 판정에 불필요하면서
민감도가 높은 주민등록번호·계좌번호·전화번호만 자리표시자로 치환한다.

패턴은 형식만으로 구분 가능한 것(주민등록번호·전화번호)은 라벨 없이도 마스킹하고,
계좌번호처럼 은행마다 자릿수·구분자가 제각각이라 형식만으로는 날짜("2026-05-03")
같은 정상 값과 구분하기 어려운 것은 "계좌"/"계좌번호" 같은 라벨이 붙어 있을 때만
마스킹한다 (과잉 마스킹으로 날짜를 지워버리는 것을 방지).
"""

from __future__ import annotations

import re

# 주민등록번호: 6자리-7자리 (예: "901231-1234567"). 날짜(YYYY-MM-DD, 4-2-2)나
# 전화번호(0으로 시작, 2~3-3~4-4)와 자릿수 구성이 달라 형식만으로 안전하게 구분된다.
_RRN_RE = re.compile(r"\d{6}\s*-\s*\d{7}")

# 전화번호: 0으로 시작하는 지역/이동통신 번호 (예: "010-1234-5678", "02-123-4567").
# 연도가 0으로 시작하는 경우는 없으므로 날짜와 겹치지 않는다.
_PHONE_RE = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")

# 계좌번호: 은행마다 자릿수·구분자가 제각각이라 "계좌"류 라벨이 붙어 있을 때만
# 그 뒤에 오는 숫자·하이픈 덩어리를 마스킹한다.
_ACCOUNT_LABEL_RE = re.compile(
    r"(계좌번호|계좌|통장|입금계좌)(\s*[:：]?\s*)([0-9][0-9\-]{7,})"
)


def _mask_account(match: re.Match[str]) -> str:
    label, spacer, _digits = match.group(1), match.group(2), match.group(3)
    return f"{label}{spacer}[계좌번호]"


def mask_text(text: str) -> str:
    """주민등록번호·계좌번호·전화번호만 자리표시자로 치환한 텍스트를 반환한다."""
    masked = _RRN_RE.sub("[주민등록번호]", text)
    masked = _PHONE_RE.sub("[전화번호]", masked)
    masked = _ACCOUNT_LABEL_RE.sub(_mask_account, masked)
    return masked
