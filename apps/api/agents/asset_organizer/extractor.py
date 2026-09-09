# TODO: decedent_estate의 llm_client.py와 로직이 중복됨.
# agents/common/ 공유 모듈로 빼는 방안을 지원과 확인 후 통합할 것.
# 그 전까지는 의도적으로 로컬 복제 상태로 둠 (cross-agent import 방지).

"""
자연어 → 자산/소득 슬롯 추출 (정규식 1차 → LLM 폴백).

⚠️ 조용한 실패 금지 원칙 (decedent_estate에서 반복됐던 버그 유형 — LLM 응답
파싱 실패를 except가 삼킴, mock이 실제 응답 형태를 못 잡음, 환경변수 이름
불일치 — 를 피하려고 아래처럼 설계했다):
- 정규식도 LLM도 값을 확정하지 못하면 절대 0이나 빈 값으로 채우지 않는다.
  대신 ExtractionResult.missing 에 "무엇이 불명확한지"를 담아 status를
  "needs_clarification"으로 돌려준다 — 호출부가 그 내용으로 재질문한다.
- InsuranceTag도 유형(보험)은 알지만 금액이 없으면 Asset/Liability와 동일하게
  즉시 만들지 않고 missing(kind="insurance_value")으로만 남긴다 — agent.py가
  한 번 후속 질문("몰라요"도 답으로 인정)을 던져 confirmed/unknown_amount를
  가른 뒤에야 InsuranceTag를 만든다(models.InsuranceTag.confidence 참고).
  단, 이 함수(정규식 1차 추출)가 같은 세그먼트 안에서 "몰라요/모르겠어요"
  까지 이미 확인했다면(예: "보험은 있는데 금액은 몰라요") 후속 질문 없이
  바로 unknown_amount로 확정한다 — 사용자가 먼저 답을 준 걸 다시 캐묻지
  않는다는 원칙(부채/자산 동일)의 연장.
- 환경변수는 decedent_estate/llm_client.py와 동일하게 ANTHROPIC_API_KEY
  하나로 통일한다. 키가 없으면 예외 없이 그냥 LLM 단계를 건너뛴다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Optional

import anthropic

from .models import Asset, AssetType, IncomeStream, InsuranceTag, Liability

#: extractor가 실제로 알아보는 부채 유형. models.Liability.type은
#: tax_calculator 등 다른 소비자를 고려해 plain str로 열려 있지만, 여기서는
#: 정규식 키워드 사전의 키를 좁혀두기 위한 로컬 타입일 뿐이다.
_LiabilityLabel = Literal["대출", "카드론", "전세자금대출", "임대보증금반환채무"]

_MODEL = os.getenv("CLAUDE_EXTRACT_MODEL", "claude-haiku-4-5-20251001")
_TIMEOUT_SECONDS = 8.0
_MAX_TOKENS = 400


def _build_system_prompt() -> str:
    """LLM에게 보내는 시스템 프롬프트. assets 필드의 허용 유형 목록은
    _VALID_ASSET_TYPES(= _ASSET_KEYWORDS.keys() + "기타")에서 직접
    파생한다 — 새 자산 유형을 _ASSET_KEYWORDS에 추가하기만 하면 이
    프롬프트 문구도 자동으로 따라오고, 화이트리스트와 프롬프트가 서로
    어긋날 일이 없다(수동 동기화 불필요). 호출 시점에 조립하는 이유는
    _VALID_ASSET_TYPES가 이 함수보다 파일 아래쪽(LLM 폴백 섹션)에서
    정의되기 때문 — 모듈 로드가 끝난 뒤 호출되므로 문제없다.

    ⚠️ P0 버그의 방어선 2(보조): 실제 수정은 extract_financial_slots()가
    _match_liability_type()으로 식별되는 세그먼트를 애초에 이 LLM 호출
    후보에서 제외하는 것이다(구조적 제외, 이 함수 밖) — 아래 부채 관련
    지시문은 그 필터를 우회하는 다른 경로(예: 필터를 통과한 세그먼트 안에
    부채 언급이 섞여 있는 경우)에 대비한 보조 방어선일 뿐, 이 프롬프트
    문구 하나로 버그를 고쳤다고 보지 않는다."""
    asset_types = "|".join(_VALID_ASSET_TYPES)
    return (
        "너는 사용자의 자연어 발화에서 금융자산·소득·보험 정보를 추출하는 도구다.\n"
        "정규식으로 못 잡은 표현만 너에게 온다. 절대 판정하거나 조언하지 마라 — "
        "너는 오직 값 추출만 한다.\n"
        "대출·카드론·전세자금대출·임대보증금반환채무 등 부채(빚) 관련 언급은 "
        "assets에 절대 포함하지 마라 — 부채는 이 도구가 다루는 범위가 아니고, "
        "별도 시스템이 처리한다. 부채로 보이는 표현은 assets에도 unclear에도 "
        "넣지 말고 그냥 무시하라.\n"
        "금액이나 나이를 확실히 알 수 없으면 절대 숫자를 지어내지 마라 — 그 항목은 "
        "생략하고 unclear 배열에 이유를 적어라.\n"
        "반드시 아래 JSON 형식으로만 답하라. 코드블록이나 다른 설명을 절대 덧붙이지 "
        "마라.\n"
        "{\n"
        '  "assets": [{"type": "' + asset_types + '", "value": 원단위 정수}],\n'
        '  "incomes": [{"type": "국민연금|개인연금|기타", "monthly": 원단위 정수, '
        '"start_age": 정수}],\n'
        '  "insurance": [{"value": 원단위 정수 또는 null}],\n'
        '  "unclear": ["무엇을 확인하지 못했는지에 대한 짧은 설명"]\n'
        "}"
    )


@dataclass
class ExtractionResult:
    """추출 결과. status가 "needs_clarification"이어도 이미 확정된 항목은
    assets/incomes/insurance_tags 에 그대로 담겨 있다 — 재질문은 missing에
    적힌 항목에 대해서만 하면 된다(전체를 다시 묻지 않는다)."""

    status: Literal["ok", "needs_clarification"]
    assets: list[Asset] = field(default_factory=list)
    incomes: list[IncomeStream] = field(default_factory=list)
    insurance_tags: list[InsuranceTag] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)


# --------------------------------------------------------------------- 정규식


#: ⚠️ 이 파일의 금액 파싱 로직(_NOISE_RE/_UNIT_MULTIPLIERS/_UNIT_RE/
#: _parse_amount/_THOUSANDS_COMMA_RE)은 agents/retirement_planner/agent.py에
#: 그대로 로컬 복제돼 있다(cross-agent import 금지 원칙, 그쪽 docstring도
#: 동일하게 명시) — 여기를 고치면 그쪽도 반드시 같이 고칠 것. AssetType
#: 중복과 같은 문제 클래스라 agents/common/ 공유 모듈 후보로 이미 CLAUDE.md
#: 미해결 항목에 있음.
_NOISE_RE = re.compile(r"정도|쯤|가량|약|한(?=\s*\d)")
#: "3,200"처럼 천 단위 구분 콤마로 숫자 안에 낀 것만 제거한다(리스트 구분자
#: 콤마와는 lookaround로 구분 — 숫자-콤마-숫자만 대상). _parse_amount에서
#: _UNIT_RE 매칭 전에 적용해 "3,200만원"이 "200만원"으로 잘리는 걸 막는다
#: (실측 버그: 콤마 뒤 숫자만 단위와 결합돼 앞자리가 통째로 날아갔었다).
_THOUSANDS_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_UNIT_MULTIPLIERS: dict[str, int] = {
    "조": 1_000_000_000_000,
    "억": 100_000_000,
    "천만": 10_000_000,
    "백만": 1_000_000,
    # 구어체 "3천"은 자산 규모를 말할 때 "3천만원"의 축약 표현으로 흔히
    # 쓰인다("예금 3천 있어요" 등) — 그래서 "만"이 안 붙은 "천"도 천만원
    # 단위로 해석한다. "3천원"처럼 소액을 뜻하는 경우와 구분할 방법이 없어
    # 생기는 의도적 트레이드오프이며, 이 에이전트가 다루는 노후자금 규모
    # 맥락에서는 전자가 훨씬 흔하다고 판단했다 (알려진 한계로 남겨둠).
    "천": 10_000_000,
    # "백"도 "천"과 같은 이유의 트레이드오프 — "6천5백"처럼 "천" 뒤에 붙는
    # "5백"은 이 도메인에서 "5백만원"의 축약이다(실측 재현: A1 자연어 탐색
    # 라운드, "예금은 한 6천5백 정도 있고" → 65,000,000). 숫자가 앞에 붙어야만
    # (_UNIT_RE가 자릿수를 요구) 매칭되므로 "백만원"(리터럴 100만원, 이미
    # "백만" 키로 별도 처리됨)과 혼동되지 않는다.
    "백": 1_000_000,
    "만": 10_000,
    "원": 1,
}
_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(조|억|천만|백만|천|백|만|원)")
#: 실측 재현(D2, 자연어 탐색): "펀드는 천만원 있어요"처럼 앞에 숫자가 전혀
#: 안 붙은 순수 한글 단위어("천만원", "만원", "억원" 등)는 위 _UNIT_RE가
#: 숫자를 필수로 요구해 아예 못 잡는다. 다만 숫자 없이 단위어만 임의로
#: 아무 데서나 인식하면 "억울하다"("억"으로 시작), "원한"("원"으로 시작)
#: 처럼 돈과 무관한 단어를 오인식할 위험이 크다 — 그래서 반드시 (1) 단어
#: 시작 지점(공백/문장부호/세그먼트 시작)에서 시작하고 (2) 단위어 바로
#: 뒤에 "원"이 붙어서 끝나고(그래야 "만약"/"천천히"처럼 다른 글자로 이어지는
#: 경우가 걸러진다) (3) 그 뒤가 공백/문장부호/세그먼트 끝이어야만 매칭한다.
_BARE_UNIT_WORD_RE = re.compile(
    r"(?:^|(?<=\s))(조|억|천만|백만|천|백|만)원(?=\s|$|[.,?!])"
)


def _parse_amount(text: str) -> Optional[int]:
    """텍스트에서 원화 금액을 찾아 정수(원)로 돌려준다. 못 찾으면 None —
    절대 0으로 대체하지 않는다 (호출부가 missing 처리 여부를 결정)."""
    cleaned = _NOISE_RE.sub("", text)
    cleaned = _THOUSANDS_COMMA_RE.sub("", cleaned)
    matches = _UNIT_RE.findall(cleaned)
    bare_matches = _BARE_UNIT_WORD_RE.findall(cleaned)
    if not matches and not bare_matches:
        return None
    total = Decimal("0")
    for number, unit in matches:
        total += Decimal(number) * _UNIT_MULTIPLIERS[unit]
    for unit in bare_matches:
        total += _UNIT_MULTIPLIERS[unit]
    return int(total)


#: agent.py의 _NEGATIVE_ANSWER_RE와 같은 패턴(로컬 복제 — extractor.py가
#: agent.py를 import하면 순환참조가 생겨 의도적으로 분리했다). 유형 키워드가
#: 매칭된 세그먼트에 부정 표현이 같이 있으면("대출은 없어요") "그 유형은
#: 있는데 금액을 모른다"가 아니라 "그 유형 자체가 없다"는 뜻이다 — 실측
#: 재현된 버그: 이 구분이 없어서 "대출은 없어요"가 대출 존재를 확정하고
#: 금액만 되묻는 상태로 잘못 처리됐다(Round 15).
_SEGMENT_NEGATION_RE = re.compile(r"없|아니")
#: agent.py의 _DONT_KNOW_AMOUNT_RE와 같은 패턴의 로컬 복제본 — extractor는
#: agent를 import할 수 없어(agent가 extractor를 import하는 방향, 순환 참조
#: 방지) 공유할 수 없다. "보험은 있는데 금액은 몰라요"처럼 정규식 1차
#: 추출 단계에서 바로 unknown_amount로 확정하려면 이 파일 안에서도 판단이
#: 필요하다(_NOISE_RE 등 기존 로컬 복제 관례와 동일). "확인 못 했어요"/
#: "확인 안 됐어요"도 "몰라요"와 같은 뜻으로 흔히 쓰이는 구어체 표현이라
#: 같이 인식한다(실측 재현 B3: "증권 계좌는 있다고 하는데 잔액은 아직
#: 확인 못 했어요").
_DONT_KNOW_AMOUNT_RE = re.compile(r"몰라|모르|확인.{0,6}(?:못|안)")
_ASSET_KEYWORDS: dict[AssetType, tuple[str, ...]] = {
    # "통장"은 이 제품 문맥에서 "예금"의 흔한 구어체 동의어다(실측 재현
    # A2, 자연어 탐색 라운드: "통장에 3200만원 정도 있고").
    "예금": ("예금", "적금", "저금", "통장"),
    # "증권"은 "증권 계좌"처럼 주식·투자상품 보유를 가리키는 구어체
    # 동의어다(실측 재현 B3: "증권 계좌는 있다고 하는데 잔액은...").
    "주식": ("주식", "증권"),
    "펀드": ("펀드",),
    "부동산": ("집", "아파트", "주택", "부동산", "건물"),
    "자동차": ("자동차", "차량"),
    "퇴직연금": ("퇴직연금",),
}
_INSURANCE_KEYWORDS = ("보험",)
# 마침표는 소수점과 구분해야 해서 숫자 사이 마침표는 분리 대상에서 뺀다("3.5억" 보존).
# 콤마도 마찬가지로 천 단위 구분자("3,200")와 나열 구분자("1억, 주식 5천만원")를
# 구분해야 한다 — 숫자 사이 콤마는 분리 대상에서 뺀다(실측 버그: 안 빼면
# "3,200만원"이 "3"/"200만원" 두 세그먼트로 쪼개져 앞자리가 통째로 사라졌다.
# _parse_amount의 _THOUSANDS_COMMA_RE는 이미 분리된 세그먼트 *안에서* 남은
# 콤마를 정리하는 것이라, 세그먼트 자체가 여기서 잘못 갈라지면 소용없다).
# "있고"는 콤마 없이 자산·부채를 나열할 때 흔한 연결어("예금 1억 있고 대출
# 3천만원 있어요") — 안 자르면 한 세그먼트에 숫자가 두 개 이상 섞여
# _parse_amount가 둘을 합산해버리는 실측 버그가 있었다.
# "(?<=없)고"는 "주식은 없고 펀드는 1000만원"처럼 "없고"로 이어지는 문장을
# 나눈다 — "있고"와 달리 "고" 앞의 "없"까지 통째로 지우면 그 세그먼트의
# 부정 신호(_SEGMENT_NEGATION_RE가 찾는 "없")가 함께 사라져 뒤의
# asset_absent 판정이 불가능해진다. lookbehind로 "고" 한 글자만 구분자로
# 삼아 "없"은 앞 세그먼트에 남긴다(D-01).
# ⚠️ 실측 재현된 버그(자연어 탐색 라운드): "아파트는 3억5천이고 카드론은
# 3천만원 남아 있다고 합니다"/"예금이 5천만원이랑 집이 4억 있습니다"/
# "예금은 8천 정도? 대출은 1억 조금 넘게 남았습니다"처럼 "이고"/"이랑"/
# 물음표로 이어지는 문장은 기존 구분자(있고/그리고/또한/콤마/마침표)에
# 안 걸려 한 세그먼트로 남았다 — _parse_amount가 세그먼트 안의 모든
# 금액을 합산하는 방식이라(예: "3,200만원" 같은 복합 단위 표기를 한
# 숫자로 합치기 위한 설계) 서로 다른 자산·부채 두 개의 금액이 하나로
# 더해져 둘 다 잘못된(부풀려진) 값으로 등록되거나, 두 번째 유형이
# 완전히 유실됐다. "이고"/"이랑"은 콤마 없이 자산·부채를 나열할 때
# "있고"만큼 흔한 연결어이고, "?"는 "8천 정도?"처럼 망설이는 어조에서
# 흔히 문장 중간의 구두점으로 쓰인다 — 셋 다 구분자로 추가한다.
# "정도고"는 "정도이고"의 구어체 축약("2억8천 정도고 자동차도...")으로,
# "있고"/"이고"만큼 흔하진 않지만 근사치 표현 뒤에 특히 자주 붙는다(실측
# 재현 A1) — 일반적인 "-고" 전부를 구분자로 넣으면 "정리하려고"/"남아
# 있다고" 같은 무관한 표현까지 과잉 분리되므로, 이 특정 축약형만 좁게
# 추가한다.
_SEGMENT_SPLIT_RE = re.compile(
    r"(?<!\d)[.](?!\d)|(?<!\d),(?!\d)|、|\?|그리고|또한|있고|이고|이랑|정도고|(?<=없)고"
)
#: 순수 조사만 남았는지 확인 — "주식,"처럼 콤마로 나열된 세그먼트가 키워드
#: 자체 그대로("주식")이거나 조사만 붙었으면("자동차는") 서술어 없는 "맨
#: 명사" 나열로 보고, 뒤에 나오는 부정 표현이 이 나열 전체에 걸리는지
#: 판단하는 데 쓴다(D-01, _regex_extract의 bare_buffer 참고).
_PARTICLE_ONLY_RE = re.compile(r"^[은는이가도\s]*$")


def _match_asset_type(segment: str) -> Optional[AssetType]:
    for asset_type, keywords in _ASSET_KEYWORDS.items():
        if any(keyword in segment for keyword in keywords):
            return asset_type
    return None


#: "차"는 자산 키워드 사전에 raw 한 글자로 그냥 추가하면 "차이"/"차례"/
#: "기차"/"세차" 등과 충돌해 오탐이 크다(D3, 자연어 탐색 라운드에서
#: 명시적으로 금지됨). 그래서 키워드 사전에는 넣지 않고, "차"가 독립
#: 명사로 쓰인 좁은 형태(조사 는/가/도가 바로 붙거나 "차 한 대"처럼
#: 쓰이거나 세그먼트 전체가 "차" 그 자체인 경우)만 별도로 인식한다.
#: 앞이 세그먼트 시작이거나 공백/문장부호 뒤여야 한다 — "기차는"처럼 다른
#: 한글 음절에 바로 붙은 "차"는 이 lookbehind에서 막힌다.
_CAR_COLLOQUIAL_RE = re.compile(r"(?:^|(?<=[\s,.!?]))차(?=는|가|도|\s*한\s*대|$)")


def _match_all_asset_types(segment: str) -> list[tuple[AssetType, str]]:
    """세그먼트 안에서 매칭되는 모든 자산 유형을 (유형, 실제 매칭된 키워드)
    쌍으로 돌려준다. "주식과 펀드는 없어요"처럼 부정 표현 하나가 콤마 없이
    유형 두 개를 한 세그먼트 안에서 함께 가리키는 경우, 기존
    _match_asset_type(첫 매칭만 반환)로는 두 번째 유형을 통째로 놓친다
    (D-01)."""
    matches: list[tuple[AssetType, str]] = []
    for asset_type, keywords in _ASSET_KEYWORDS.items():
        for keyword in keywords:
            if keyword in segment:
                matches.append((asset_type, keyword))
                break
    if not any(asset_type == "자동차" for asset_type, _ in matches):
        if _CAR_COLLOQUIAL_RE.search(segment):
            matches.append(("자동차", "차"))
    return matches


def _is_bare_type_segment(segment: str, keyword: str) -> bool:
    """세그먼트가 서술어 없이 유형 이름(+조사)만 있는 "맨 명사" 나열인지
    판단한다. "주식, 펀드, 자동차, 퇴직연금, 보험은 없어요."처럼 쉼표로
    나열된 항목들은 각자 분리된 세그먼트("주식", "펀드", ...)가 되지만
    자신은 부정 표현을 담고 있지 않다 — 나열 맨 끝에 오는 서술어(마지막
    항목의 "~은 없어요")가 전체 나열에 걸리는지 판단하려면 먼저 이런 맨
    명사 세그먼트를 구분해야 한다(D-01)."""
    residual = segment.replace(keyword, "", 1)
    return bool(_PARTICLE_ONLY_RE.fullmatch(residual))


def _regex_extract(text: str) -> tuple[ExtractionResult, list[str]]:
    """정규식 1차 파싱. (지금까지 확정된 결과, 정규식이 유형조차 못 알아본
    세그먼트 목록)을 함께 돌려준다 — 후자는 LLM 폴백 대상이 된다."""
    segments = [s.strip() for s in _SEGMENT_SPLIT_RE.split(text) if s.strip()]

    assets: list[Asset] = []
    insurance_tags: list[InsuranceTag] = []
    missing: list[dict[str, Any]] = []
    unresolved: list[str] = []

    # "주식, 펀드, 자동차, 퇴직연금, 보험은 없어요."처럼 쉼표로 나열된 맨
    # 명사 세그먼트("주식", "펀드", ...)는 그 자체로는 부정 표현이 없어
    # asset_absent로 즉시 판단할 수 없다 — 나열 끝에 오는 서술어("보험은
    # 없어요")가 나와야만 앞선 나열 전체가 부정된 것인지 알 수 있다. 그래서
    # 판단을 뒤로 미루고 bare_buffer에 쌓아 둔다(D-01). 중간에 금액이 있는
    # 세그먼트나 유형을 못 알아본 세그먼트가 끼면 나열이 끊긴 것이므로,
    # 그 시점까지 쌓인 항목은 부정될 기회를 잃은 것으로 보고 기존처럼
    # "금액 미확인" 재질문 대상으로 되돌린다(flush_as_missing) — 조용한
    # 실패 금지 원칙을 유지하면서 나열 해석에서만 예외를 둔다.
    bare_buffer: list[tuple[str, AssetType]] = []

    def flush_as_missing() -> None:
        for seg, atype in bare_buffer:
            missing.append(
                {
                    "kind": "asset_value",
                    "asset_type": atype,
                    "segment": seg,
                    "reason": f"{atype} 금액이 언급되지 않음",
                }
            )
        bare_buffer.clear()

    def flush_as_absent() -> None:
        for seg, atype in bare_buffer:
            missing.append(
                {"kind": "asset_absent", "asset_type": atype, "segment": seg}
            )
        bare_buffer.clear()

    for segment in segments:
        is_negated = bool(_SEGMENT_NEGATION_RE.search(segment))

        if any(keyword in segment for keyword in _INSURANCE_KEYWORDS):
            if is_negated:
                # "보험은 없어요" — 보험 자체가 없다는 확정 답변이다.
                # asset_absent와 동일한 이유로 금액 재질문 대상이 아니다.
                flush_as_absent()
                missing.append(
                    {"kind": "asset_absent", "asset_type": "보험", "segment": segment}
                )
                continue
            flush_as_missing()
            amount = _parse_amount(segment)
            if amount is not None:
                insurance_tags.append(
                    InsuranceTag(type="보험", value=amount, confidence="confirmed")
                )
            elif _DONT_KNOW_AMOUNT_RE.search(segment):
                # "보험은 있는데 금액은 몰라요" — 후속 질문 없이 바로
                # unknown_amount로 확정한다(먼저 답을 준 걸 다시 캐묻지 않음).
                insurance_tags.append(
                    InsuranceTag(type="보험", value=None, confidence="unknown_amount")
                )
            else:
                missing.append(
                    {
                        "kind": "insurance_value",
                        "asset_type": "보험",
                        "segment": segment,
                        "reason": "보험 금액이 언급되지 않음",
                    }
                )
            continue

        matched_types = _match_all_asset_types(segment)
        if not matched_types:
            flush_as_missing()
            unresolved.append(segment)
            continue

        amount = _parse_amount(segment)
        if amount is not None:
            # 금액이 있는 세그먼트가 나오면 그 전까지 쌓인 맨 명사 나열은
            # 부정으로 끝나지 못한 것 — 기존처럼 금액 재질문 대상으로 되돌린다.
            flush_as_missing()
            asset_type = matched_types[0][0]
            assets.append(Asset(type=asset_type, value=amount))
            continue

        if is_negated:
            # "주식과 펀드는 없어요"(한 세그먼트에 유형 2개) 또는 나열 끝의
            # "보험은 없어요" 같은 서술어 세그먼트 — 여기서 발견된 부정은
            # 이 세그먼트가 가리키는 유형(들)뿐 아니라, 서술어 없이 먼저
            # 나열됐던 bare_buffer 항목 전체에도 적용된다.
            flush_as_absent()
            for asset_type, _keyword in matched_types:
                missing.append(
                    {
                        "kind": "asset_absent",
                        "asset_type": asset_type,
                        "segment": segment,
                    }
                )
            continue

        if len(matched_types) == 1 and _is_bare_type_segment(
            segment, matched_types[0][1]
        ):
            # 서술어 없는 맨 명사 세그먼트 — 뒤에 부정 표현이 나올 때까지
            # 판단을 미룬다.
            bare_buffer.append((segment, matched_types[0][0]))
            continue

        # 유형은 확인됐지만 금액이 없고, 부정도 아니고, 맨 명사 나열도
        # 아니다(예: "집 한 채 있어요"). Asset.value는 engine.simulate()의
        # 잔액 계산에 직접 쓰이므로, InsuranceTag와 달리 값을 지어내면
        # 시뮬레이션 결과가 조용히 틀려진다 — 그래서 Asset을 만들지 않고
        # 후속 질문 대상으로만 남긴다.
        flush_as_missing()
        asset_type = matched_types[0][0]
        if _DONT_KNOW_AMOUNT_RE.search(segment):
            # "자동차도 있는데 지금 얼마인지는 모르겠네요"처럼 같은 세그먼트
            # 안에서 이미 "모르겠다"고 답했다면(보험의 기존 동일 원칙, 위
            # 참고) 후속 질문 없이 바로 unknown_amount로 확정한다 — 사용자가
            # 먼저 답을 준 걸 다시 캐묻지 않는다(실측 재현 A1/D3).
            assets.append(Asset(type=asset_type, value=0, confidence="unknown_amount"))
        else:
            missing.append(
                {
                    "kind": "asset_value",
                    "asset_type": asset_type,
                    "segment": segment,
                    "reason": f"{asset_type} 금액이 언급되지 않음",
                }
            )

    # 나열이 부정으로 끝나지 못하고 문장이 끝났다("주식, 펀드" 뒤에 아무
    # 서술어도 안 옴) — 기존처럼 개별 금액 재질문 대상으로 처리한다.
    flush_as_missing()

    status: Literal["ok", "needs_clarification"] = (
        "needs_clarification" if missing or unresolved else "ok"
    )
    result = ExtractionResult(
        status=status,
        assets=assets,
        incomes=[],
        insurance_tags=insurance_tags,
        missing=missing,
    )
    return result, unresolved


_LIABILITY_KEYWORDS: dict[_LiabilityLabel, tuple[str, ...]] = {
    "대출": ("대출", "융자", "빚"),
    "카드론": ("카드론",),
    "전세자금대출": ("전세자금대출", "전세대출"),
    "임대보증금반환채무": ("임대보증금", "보증금반환", "보증금 반환"),
}

#: "재산이랑 빚을 정리해두려고 해요"/"자산과 부채를 확인하고 싶어요"처럼
#: 자산·부채를 뭉뚱그려 "정리/확인하겠다"는 포괄적 상담 의도 표현. "빚"만
#: 문제가 된다 — "대출"/"융자"/"카드론"/"전세자금대출"/"임대보증금"은
#: 이런 포괄 의도 문장에 자연스럽게 등장하지 않는 구체적 금융상품
#: 명사라 이 가드가 필요 없다(실측: "빚"만 일상어라 "부채"의 대용으로도
#: 흔히 쓰임). "정리"/"확인" + 의향형 어미(-려고/-고 싶/-줄래 등)가 함께
#: 있어야만 좁게 잡는다 — 이미 완료된 사실 진술("정리했어요")은 이 어미가
#: 없어 안 걸린다.
_ORGANIZE_INTENT_RE = re.compile(
    r"(정리|확인)(하|해)\S{0,6}(려고|고\s*싶|줄래|주세요|볼까)"
)
#: 위 포괄 의도 표현이라도 "빚이 있는데"/"빚이 남아"처럼 존재를 실제로
#: 진술하는 구절이 같은 세그먼트에 있으면 억제하지 않는다 — "빚이 좀
#: 있는데 정리하고 싶어요"는 실제 부채 존재 확인이 우선이다. "없|아니"
#: (부정)와 대칭으로 짧은 로컬 조각 매칭 관례(_NEGATIVE_ANSWER_RE 등)를
#: 그대로 따른다.
#: ⚠️ 실측 재현된 버그(자연어 탐색 2라운드, C3): "빚이 뭐가 있는지
#: 정리해두려고 해요"의 "있는지"는 존재를 진술하는 게 아니라 "뭐가
#: 있는지 (모르니 확인하고 싶다)"는 질문형 어미다. 이 "있"까지 존재
#: 진술로 오인하면 위 가드가 억제되지 않아, 확정되지 않은 부채에 대해
#: "얼마 남았나요"까지 되묻는 잘못된 후속 질문이 나갔다. "있는지"만
#: 좁게 제외한다 — "있는데"/"있어요"/"있대요" 등 실제 존재 진술은
#: 그대로 걸린다.
_EXISTENCE_VERB_RE = re.compile(r"있(?!는지)|남")


def _is_generic_liability_intent(segment: str, keyword: str) -> bool:
    """실측 재현된 버그: 사후 모드 첫 턴에서 "재산이랑 빚을 정리해두려고
    해요"라고만 말해도 "빚" 키워드가 잡혀 대출 존재가 확정되고 곧바로
    대출 금액을 되물었다 — 구체적 보유 항목이 없으므로 category selection
    으로 가야 했다. "빚" 키워드가 매칭됐고, 포괄적 정리/확인 의도
    표현이면서, 존재를 실제로 진술하는 구절이 없을 때만 이 키워드
    매칭을 무시한다."""
    if keyword != "빚":
        return False
    if not _ORGANIZE_INTENT_RE.search(segment):
        return False
    return not _EXISTENCE_VERB_RE.search(segment)


def _match_liability_type(segment: str) -> Optional[_LiabilityLabel]:
    for liability_type, keywords in _LIABILITY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in segment and not _is_generic_liability_intent(
                segment, keyword
            ):
                return liability_type
    return None


def extract_liabilities(text: str) -> tuple[list[Liability], list[dict[str, Any]]]:
    """부채 언급을 정규식으로 1차 추출한다. (확정된 부채 목록, 유형은 알지만
    금액이 없어 후속 질문이 필요한 항목) 을 돌려준다.

    remaining_balance만 채운다 — monthly_payment/end_age(정밀 모드 판단
    기준, engine.py 참고)는 이번 라운드에서 자연어 추출을 시도하지 않는다.
    "3년 남았어요"처럼 상대적인 표현을 절대 나이(end_age)로 바꾸려면
    current_age가 필요한데, 이 함수는 문장만 보고 그 맥락이 없다 — 억지로
    떠맡기면 조용히 틀린 나이를 지어낼 위험이 있어 차라리 두 필드는 항상
    None으로 남기고 (자동으로 단순 모드로 계산됨) 구조적 지원만 해둔다.
    자산 추출과 달리 LLM 폴백도 두지 않는다 — 별도 호출을 또 태우기엔
    비용 대비 효과가 낮다고 판단했고, 정규식이 못 잡으면 호출부(agent.py의
    대화형 흐름)가 일반적인 카테고리 확인 질문으로 다시 물어본다.
    """
    segments = [s.strip() for s in _SEGMENT_SPLIT_RE.split(text) if s.strip()]
    liabilities: list[Liability] = []
    missing: list[dict[str, Any]] = []

    for segment in segments:
        liability_type = _match_liability_type(segment)
        if liability_type is None:
            continue

        amount = _parse_amount(segment)
        if amount is None:
            if _SEGMENT_NEGATION_RE.search(segment):
                # _regex_extract의 asset_absent와 같은 이유 — "대출은
                # 없어요"는 대출 존재 확정이 아니라 부재 확정이다.
                missing.append(
                    {
                        "kind": "liability_absent",
                        "liability_type": liability_type,
                        "segment": segment,
                    }
                )
                continue
            if _DONT_KNOW_AMOUNT_RE.search(segment):
                # "대출은 있는데 얼마 남았는지는 잘 모르겠어요"처럼 같은
                # 세그먼트 안에서 이미 "모르겠다"고 답했다면 보험/자산과
                # 동일한 원칙으로 후속 질문 없이 바로 unknown_amount로
                # 확정한다(실측 재현 B2) — remaining_balance는 Liability의
                # 불변식대로 반드시 None.
                liabilities.append(
                    Liability(
                        type=liability_type,
                        remaining_balance=None,
                        confidence="unknown_amount",
                    )
                )
                continue
            missing.append(
                {
                    "kind": "liability_value",
                    "liability_type": liability_type,
                    "segment": segment,
                    "reason": f"{liability_type} 금액이 언급되지 않음",
                }
            )
            continue

        liabilities.append(Liability(type=liability_type, remaining_balance=amount))

    return liabilities, missing


def parse_monthly_expense_answer(text: str) -> Optional[int]:
    """ "생활비는 200만원 정도예요" 같은, 월 생활비를 묻는 질문에 대한 단답형
    답변에서 금액만 뽑는다. 단일 숫자 답변까지 LLM을 태우는 건 과하다고 판단해
    LLM 폴백은 두지 않는다 — 실패하면 호출부가 그대로 재질문하면 된다."""
    return _parse_amount(text)


# ------------------------------------------------------------------ LLM 폴백


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_code_fence(text: str) -> str:
    """LLM이 프롬프트 지시를 무시하고 ```json ... ``` 코드펜스로 감싸 응답하는
    경우를 대비한 방어적 제거."""
    return _CODE_FENCE_RE.sub("", text.strip()).strip()


def _parse_json_response(text: str) -> Optional[dict[str, Any]]:
    try:
        parsed = json.loads(_strip_code_fence(text))
    except (json.JSONDecodeError, AttributeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _client() -> Optional[anthropic.Anthropic]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _llm_extract(text: str) -> Optional[dict[str, Any]]:
    client = _client()
    if client is None:
        return None

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_build_system_prompt(),
            messages=[{"role": "user", "content": text}],
            timeout=_TIMEOUT_SECONDS,
        )
        return _parse_json_response(response.content[0].text)
    except Exception:
        # 네트워크 오류·타임아웃·응답 형식 오류 등 어떤 이유든 재질문 경로로
        # 넘긴다 (조용히 삼키고 0/빈 값으로 채우지 않는다).
        return None


_VALID_ASSET_TYPES = (*_ASSET_KEYWORDS.keys(), "기타")
_VALID_INCOME_TYPES = ("국민연금", "개인연금", "기타")


def _apply_llm_payload(
    payload: dict[str, Any],
) -> tuple[list[Asset], list[IncomeStream], list[InsuranceTag], list[dict[str, Any]]]:
    assets: list[Asset] = []
    incomes: list[IncomeStream] = []
    insurance_tags: list[InsuranceTag] = []
    missing: list[dict[str, Any]] = []

    for raw in payload.get("assets") or []:
        if not isinstance(raw, dict):
            continue
        asset_type = raw.get("type")
        if asset_type not in _VALID_ASSET_TYPES:
            # 화이트리스트 밖 값(오염 가능성 있는 원문)은 버리되, 항목
            # 자체는 "기타"로 보존한다 — 통째로 드롭하면 실제 자산이
            # 사용자 재무 상태에서 사라져 순자산이 실제보다 적어 보이게
            # 왜곡된다(부채 쪽과 대칭 — 이쪽은 "실제보다 나빠 보임" 방향
            # 이지만 마찬가지로 사실과 다른 왜곡이라 안전하지 않다).
            asset_type = "기타"
        value = raw.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            missing.append(
                {
                    "kind": "asset_value",
                    "asset_type": asset_type,
                    "reason": f"{asset_type} 금액을 LLM도 확인하지 못함",
                }
            )
            continue
        assets.append(Asset(type=asset_type, value=int(value)))

    for raw in payload.get("incomes") or []:
        if not isinstance(raw, dict):
            continue
        income_type = raw.get("type")
        if income_type not in _VALID_INCOME_TYPES:
            # 자산과 동일한 이유로 "기타"로 보존한다(항목 자체는 안 버림).
            income_type = "기타"
        monthly = raw.get("monthly")
        start_age = raw.get("start_age")
        valid_monthly = isinstance(monthly, (int, float)) and not isinstance(
            monthly, bool
        )
        valid_start_age = isinstance(start_age, int) and not isinstance(start_age, bool)
        if not valid_monthly or not valid_start_age:
            missing.append(
                {
                    "kind": "income_detail",
                    "income_type": income_type,
                    "reason": "소득 월액 또는 개시 나이를 확인하지 못함",
                }
            )
            continue
        incomes.append(
            IncomeStream(type=income_type, monthly=int(monthly), start_age=start_age)
        )

    for raw in payload.get("insurance") or []:
        if not isinstance(raw, dict):
            continue
        value = raw.get("value")
        has_value = isinstance(value, (int, float)) and not isinstance(value, bool)
        if has_value:
            insurance_tags.append(
                InsuranceTag(type="보험", value=int(value), confidence="confirmed")
            )
        else:
            # 금액 없이도 즉시 확정하지 않는다 — agent.py의 후속 질문 대상으로
            # 남긴다(_regex_extract의 동일 분기 원칙, models.InsuranceTag 참고).
            missing.append(
                {
                    "kind": "insurance_value",
                    "asset_type": "보험",
                    "reason": "보험 금액을 LLM도 확인하지 못함",
                }
            )

    # ⚠️ PII 잔여 위험 지점: "unclear"는 자산/부채/소득 type과 달리 화이트리스트가
    # 없는 완전 자유텍스트라 LLM이 (프롬프트가 금지해도) 계좌번호·이름 등을
    # 그대로 적어 보낼 수 있다. 지금은 agent._merge_extraction()이 kind=="asset_value"
    # 만 처리하고 이 kind는 그냥 건너뛰어서 사용자 응답·세션 저장 어디에도
    # 노출되지 않는다(실제 실행으로 확인됨 — apps/api/tests/test_asset_organizer_agent.py
    # 의 PII 관련 회귀 테스트 참고). 나중에 이 kind를 실제로 소비하는 코드를
    # 추가한다면 이 reason 원문을 그대로 노출하지 말 것 — 정형화하거나 버릴 것.
    for reason in payload.get("unclear") or []:
        if isinstance(reason, str) and reason.strip():
            missing.append({"kind": "unclear", "reason": reason.strip()})

    return assets, incomes, insurance_tags, missing


def extract_financial_slots(text: str) -> ExtractionResult:
    """자연어 한 턴에서 자산·소득·보험 슬롯을 추출한다.

    흐름: 정규식으로 세그먼트별 1차 파싱 → 유형 자체를 못 알아본 세그먼트만
    모아 LLM 폴백 한 번 호출 → 그래도 안 되면(키 없음/네트워크 오류/형식
    오류) needs_clarification으로 수렴한다. 어떤 단계에서도 실패를 조용히
    삼켜 0이나 빈 값으로 채우지 않는다.
    """
    result, unresolved = _regex_extract(text)

    if not unresolved:
        return result

    # ⚠️ P0 실측 재현된 버그: "카드대출 2천만원이 확인됐어요"는 asset
    # 키워드 사전에 없어 unresolved로 넘어갔는데, 이 함수가 그 세그먼트를
    # (다른 unresolved 세그먼트와 합쳐) 그대로 asset LLM 폴백에 보내면
    # LLM이 "기타" 자산으로 반환할 수 있었다 — 같은 문장을 별도로 처리하는
    # extract_liabilities()가 이미 "대출"로 정확히 잡은 항목이 자산에도
    # 중복 등록되어 총자산이 실제보다 부채 금액만큼 부풀려졌다(요구사항
    # 4번과 대칭 원칙: 대출·카드론·전세자금대출·임대보증금반환채무 등
    # _match_liability_type()으로 부채임을 식별 가능한 세그먼트는 애초에
    # asset LLM 폴백 후보에서 제외한다 — 그 세그먼트의 소유권은 오직
    # liability extractor에게만 있다. 같은 텍스트를 처리하는
    # extract_liabilities()가 이 세그먼트를 여전히 독립적으로 보고
    # 정상 처리하므로 정보 유실이 아니다.
    llm_candidate_segments = [
        segment for segment in unresolved if _match_liability_type(segment) is None
    ]

    if not llm_candidate_segments:
        # 남은 unresolved 전부가 부채로 식별 가능한 세그먼트였다 — asset
        # 쪽은 더 이상 "이해 못함" 상태가 아니므로 LLM을 부르지 않고
        # status도 그에 맞게 되돌린다(_regex_extract는 unresolved 유무만
        # 보고 미리 "needs_clarification"을 세워뒀을 수 있다).
        result.status = "needs_clarification" if result.missing else "ok"
        return result

    # 원문 전체가 아니라 정규식이 못 알아본 세그먼트만(그중에서도 부채로
    # 식별되지 않는 것만) LLM에 넘긴다. 원문 전체를 다시 넘기면 정규식이
    # 이미 정확히 찾은 항목(예: "아파트 5억원")을 LLM이 독립적으로 또
    # 찾아내고, 그 결과가 아래에서 regex 결과에 그대로 extend()되어 같은
    # 항목이 두 번 쌓인다(실측 재현: "아파트 5억원, 예금 8천만원, 대출은
    # 없습니다" → "대출은 없습니다"만 unresolved인데도 원문 전체를 LLM에
    # 보내면 부동산·예금이 중복 생성돼 순자산이 2배로 잡혔다).
    llm_payload = _llm_extract(" ".join(llm_candidate_segments))
    if llm_payload is None:
        for segment in llm_candidate_segments:
            result.missing.append(
                {
                    "kind": "unrecognized_segment",
                    "segment": segment,
                    "reason": "자산 유형과 금액을 확인하지 못함",
                }
            )
        result.status = "needs_clarification"
        return result

    llm_assets, llm_incomes, llm_insurance, llm_missing = _apply_llm_payload(
        llm_payload
    )
    result.assets.extend(llm_assets)
    result.incomes.extend(llm_incomes)
    result.insurance_tags.extend(llm_insurance)
    result.missing.extend(llm_missing)
    result.status = "needs_clarification" if result.missing else "ok"
    return result


# --------------------------------------------------------------- 이미지 판독


#: decedent_estate/image_reader.py와 같은 이유로 원본 이미지 자체는 마스킹
#: 하지 않는다 — 마스킹하려면 먼저 읽어야 하는데, 읽는 행위(Anthropic API
#: 호출) 자체가 이미 전송이라 구조적으로 불가능하다. 대신 이 함수는 판독
#: 결과를 재구성한 텍스트를 2차 LLM 호출에 다시 태우지 않는다(한 번의
#: 멀티모달 호출로 바로 구조화된 값을 받는다) — 그래서 마스킹이 필요한
#: "재구성 텍스트가 또 LLM으로 나가는" 지점 자체가 생기지 않는다.
_IMAGE_MAX_TOKENS = 600

#: extract_from_image()이 이미지를 아예 못 읽었을 때(unreadable/네트워크
#: 오류/형식 오류/키 없음) 공통으로 쓰는 missing 항목 — agent.py가 이
#: kind를 보고 "다시 올려주세요" 재질문으로 바로 분기한다.
IMAGE_UNREADABLE_MISSING: dict[str, Any] = {
    "kind": "image_unreadable",
    "reason": "이미지를 읽지 못함 — 잘 안 보이거나 형식을 알아볼 수 없음",
}


#: 이미지 판독이 liability type으로 내놓을 수 있는 값의 전부 — extract_
#: liabilities()의 정규식 경로(_LiabilityLabel)와 동일한 화이트리스트에
#: "기타"만 더한 것(자산 쪽 _VALID_ASSET_TYPES와 같은 catch-all 관례).
#: 프롬프트가 이 값들만 쓰라고 지시하지만, 모델이 그 지시를 무시하고
#: "국민은행 대출(계좌 110-xxx, 홍길동)"처럼 계좌번호·이름이 섞인 문자열을
#: 채워 보내는 경우를 대비해 여기서 한 번 더 막는다(수집 최소화 원칙,
#: 4-6절) — 화이트리스트 밖 값은 원문(오염 가능성 있는 문자열)만 버리고
#: "기타"로 대체한다. 항목 자체를 통째로 드롭하면 실제 부채가 사용자
#: 재무 상태에서 사라져 순자산이 실제보다 좋아 보이게 왜곡된다 — PII를
#:막으려다 반대 방향으로 더 위험한 실수를 하는 셈이라, "기타"(이미 검증된
#: 정상 카테고리라 새로 추측하는 게 아님)로 보존한다.
#: 자산 쪽 _VALID_ASSET_TYPES와 동일하게 _LIABILITY_KEYWORDS.keys()에서
#: 자동 파생된다 — 새 부채 유형은 _LiabilityLabel/_LIABILITY_KEYWORDS에만
#: 추가하면 이 화이트리스트와 프롬프트 문구까지 자동으로 따라온다.
_VALID_LIABILITY_TYPES = (*_LIABILITY_KEYWORDS.keys(), "기타")


def _build_image_system_prompt() -> str:
    """이미지 판독용 시스템 프롬프트. assets/liabilities 필드의 허용 유형
    목록을 각각 _VALID_ASSET_TYPES/_VALID_LIABILITY_TYPES에서 직접
    파생한다 — _build_system_prompt()와 같은 이유(수동 동기화 불필요).
    두 화이트리스트 모두 키워드 사전(_ASSET_KEYWORDS/_LIABILITY_KEYWORDS)
    에서 자동 파생되므로, 새 유형을 그 사전에만 추가하면 화이트리스트와
    프롬프트 문구가 함께 따라온다."""
    asset_types = "|".join(_VALID_ASSET_TYPES)
    liability_types = "|".join(_VALID_LIABILITY_TYPES)
    return (
        "너는 은행 앱 잔액 화면, 안심상속 통합조회 결과 캡처 같은 이미지에서 "
        "금융자산·부채·보험 정보를 추출하는 도구다.\n"
        "절대 판정하거나 조언하지 마라 — 너는 오직 값 추출만 한다.\n"
        "화면이 흐릿하거나 무엇을 찍은 건지 알아보기 어려우면 절대 숫자를 "
        "지어내지 마라 — 그 항목은 생략하고 unclear 배열에 이유를 적어라. "
        "이미지 전체를 알아볼 수 없으면 unreadable을 true로 하라.\n"
        "수집 최소화 원칙: 자산 유형·금액, 부채 유형·잔액, 보험 가입 여부·금액"
        " 외에는 아무것도 추출하지 마라. 계좌번호·예금주명·주민등록번호·"
        "은행/지점명·카드번호·전화번호 등은 화면에 보이더라도 절대 결과에 "
        "옮기지 마라 — unclear 설명에도 그런 정보를 포함하지 마라.\n"
        "반드시 아래 JSON 형식으로만 답하라. 코드블록이나 다른 설명을 절대 "
        "덧붙이지 마라.\n"
        "{\n"
        '  "unreadable": true 또는 false,\n'
        '  "assets": [{"type": "' + asset_types + '", "value": 원단위 정수}],\n'
        '  "liabilities": [{"type": "' + liability_types + '", '
        '"remaining_balance": 원단위 정수}],\n'
        '  "insurance": [{"value": 원단위 정수 또는 null}],\n'
        '  "unclear": ["무엇을 확인하지 못했는지에 대한 짧은 설명(개인정보 제외)"]\n'
        "}"
    )


def _apply_llm_liabilities(
    raw_liabilities: Any,
) -> tuple[list[Liability], list[dict[str, Any]]]:
    """이미지 판독 JSON의 "liabilities" 배열을 Liability로 변환한다.
    extract_liabilities()의 정규식 경로와 반환 모양을 맞춘 것 — 이미지
    전용 스키마를 새로 만들지 않기 위해서다."""
    liabilities: list[Liability] = []
    missing: list[dict[str, Any]] = []

    for raw in raw_liabilities or []:
        if not isinstance(raw, dict):
            continue
        liability_type = raw.get("type")
        if liability_type not in _VALID_LIABILITY_TYPES:
            liability_type = "기타"
        value = raw.get("remaining_balance")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            missing.append(
                {
                    "kind": "liability_value",
                    "liability_type": liability_type,
                    "reason": f"{liability_type} 금액을 이미지에서 확인하지 못함",
                }
            )
            continue
        liabilities.append(Liability(type=liability_type, remaining_balance=int(value)))

    return liabilities, missing


def extract_from_image(
    image_base64: str, media_type: str
) -> tuple[ExtractionResult, list[Liability], list[dict[str, Any]]]:
    """이미지 한 장에서 자산·부채·보험을 한 번의 Claude 멀티모달 호출로
    구조화해 추출한다. 텍스트 경로(extract_financial_slots +
    extract_liabilities)와 정확히 같은 모양 — (ExtractionResult, 부채
    목록, 부채 금액 미확인 목록) — 을 돌려준다. agent.py는 두 경로를
    같은 병합 로직 하나로 처리한다.

    키가 없거나, 네트워크 오류/타임아웃/형식 오류가 나거나, 모델 스스로
    "unreadable"이라고 답하면 전부 IMAGE_UNREADABLE_MISSING 하나로
    수렴한다 — 조용히 0이나 빈 값으로 채우지 않고 재질문으로 넘긴다.
    """
    client = _client()
    if client is None:
        return (
            ExtractionResult(
                status="needs_clarification", missing=[dict(IMAGE_UNREADABLE_MISSING)]
            ),
            [],
            [],
        )

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_IMAGE_MAX_TOKENS,
            system=_build_image_system_prompt(),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "이 이미지에서 자산·부채·보험 정보를 추출해줘.",
                        },
                    ],
                }
            ],
            timeout=_TIMEOUT_SECONDS,
        )
        payload = _parse_json_response(response.content[0].text)
    except Exception:
        payload = None

    if payload is None or payload.get("unreadable") is True:
        return (
            ExtractionResult(
                status="needs_clarification", missing=[dict(IMAGE_UNREADABLE_MISSING)]
            ),
            [],
            [],
        )

    assets, incomes, insurance_tags, missing = _apply_llm_payload(payload)
    liabilities, liability_missing = _apply_llm_liabilities(payload.get("liabilities"))

    status: Literal["ok", "needs_clarification"] = (
        "needs_clarification" if (missing or liability_missing) else "ok"
    )
    result = ExtractionResult(
        status=status,
        assets=assets,
        incomes=incomes,
        insurance_tags=insurance_tags,
        missing=missing,
    )
    return result, liabilities, liability_missing


# --------------------------------------------------- 사후 모드: 조회 결과 해석


@dataclass
class DisclosureItem:
    """안심상속 원스톱서비스 등 여러 기관의 조회 결과 한 문장에서 뽑아낸
    자산 하나. 기관별로 공개 수준이 다르다는 게 핵심이라(예금·부동산·세금은
    금액까지, 보험은 가입여부만, 투자상품은 잔고 유무만 나오는 식) — 이건
    사용자가 몰라서가 아니라 기관이 애초에 그 정보를 안 준 것이다.

    ⚠️ 기관명(은행/증권사명 등)은 의도적으로 안 담는다 — extract_from_image()
    의 "수집 최소화 원칙"(계좌번호·예금주명과 함께 은행/지점명도 결과에서
    뺀다)과 동일한 이유로, 이 결과가 소비되는 지점(agent.py)까지 기관명이
    흘러갈 필요가 없다."""

    asset_type: AssetType
    confidence: Literal["confirmed", "unknown_amount"]
    value: Optional[int]  # confidence=="confirmed"일 때만 값, 아니면 None


_DISCLOSURE_MAX_TOKENS = 500
_DISCLOSURE_SYSTEM_PROMPT_TEMPLATE = (
    "너는 안심상속 원스톱서비스 등 여러 기관의 재산 조회 결과를 한 번에 "
    "설명하는 문장에서, 자산 유형별로 '금액까지 확인됐는지' 또는 '존재만 "
    "확인되고 금액은 아직 모르는지'를 구조화해서 뽑는 도구다. 기관마다 "
    "공개하는 정보 수준이 다르다는 걸 이해해야 한다 — 흔한 패턴은 예금·"
    "부동산·세금 체납은 금액까지 나오고, 보험은 가입 여부만, 주식·펀드 "
    "같은 투자상품은 잔고 유무만 나오는 식이다. 하지만 이건 참고용 "
    "패턴일 뿐, 완벽한 전 기관 커버리지를 목표로 하지 마라 — 사용자가 "
    "실제로 말한 내용을 우선하되, 금액이 명시됐는지 애매하면 반드시 "
    "unknown_amount로 표시하고 절대 금액을 지어내지 마라.\n"
    "절대 판정하거나 조언하지 마라 — 너는 오직 값 추출만 한다.\n"
    "수집 최소화 원칙: 자산 유형·확인 수준·금액 외에는 아무것도 추출하지 "
    "마라. 은행/증권사/보험사 등 기관명, 계좌번호, 예금주명, 주민등록번호, "
    "전화번호 등은 문장에 등장하더라도 절대 결과에 포함하지 마라.\n"
    "반드시 아래 JSON 형식으로만 답하라. 코드블록이나 다른 설명을 절대 "
    "덧붙이지 마라.\n"
    "{{\n"
    '  "disclosures": [{{"type": "{asset_types}", '
    '"confidence": "confirmed|unknown_amount", '
    '"value": 원단위 정수 또는 null}}]\n'
    "}}"
)


def _build_disclosure_system_prompt() -> str:
    """_build_system_prompt()와 같은 이유로 화이트리스트에서 자동 파생 —
    자산 유형이 늘어나도 이 프롬프트를 손으로 맞출 필요가 없다."""
    return _DISCLOSURE_SYSTEM_PROMPT_TEMPLATE.format(
        asset_types="|".join(_VALID_ASSET_TYPES)
    )


def _apply_disclosure_payload(payload: dict[str, Any]) -> list[DisclosureItem]:
    """LLM JSON을 DisclosureItem 리스트로 정리한다. 화이트리스트 밖 유형은
    자산 추출과 동일한 원칙으로 "기타"로 보존(드롭 안 함). confidence가
    화이트리스트 밖이거나 값 자체가 이상하면 안전한 쪽("unknown_amount")
    으로 떨어뜨린다 — 애매할 때 실제보다 좋아 보이는 쪽으로 왜곡되면
    안 되기 때문이다."""
    items: list[DisclosureItem] = []
    for raw in payload.get("disclosures") or []:
        if not isinstance(raw, dict):
            continue
        asset_type = raw.get("type")
        if asset_type not in _VALID_ASSET_TYPES:
            asset_type = "기타"

        confidence = raw.get("confidence")
        value = raw.get("value")
        valid_value = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0
        )
        if confidence == "confirmed" and valid_value:
            items.append(
                DisclosureItem(
                    asset_type=asset_type, confidence="confirmed", value=int(value)
                )
            )
        else:
            # confidence=="confirmed"인데 value가 이상해도(모델이 지시를
            # 어긴 경우) 금액을 지어내지 않고 안전하게 강등한다.
            items.append(
                DisclosureItem(
                    asset_type=asset_type, confidence="unknown_amount", value=None
                )
            )
    return items


def extract_disclosures(text: str) -> Optional[list[DisclosureItem]]:
    """사후 모드 전용: 여러 기관의 조회 결과가 섞인 문장에서 기관별 확인
    수준을 구조화해서 뽑는다. 정규식 1차 시도 없이 곧바로 LLM을 쓴다 —
    "OO은행은 잔액까지 나왔고 OO증권은 계좌만 확인됐어요" 같은 문장은
    기관명·서술 조합이 너무 다양해서 정규식으로 안정적으로 커버하기
    어렵다고 판단했다(extract_financial_slots()의 LLM 클라이언트
    인프라 — _client()/_parse_json_response()/_strip_code_fence() —
    는 그대로 재사용한다).

    ⚠️ P0(2차) 실측 재현된 버그: extract_financial_slots()의 asset LLM
    폴백에는 이미 부채로 식별되는 세그먼트를 후보에서 빼는 방어가 있는데,
    이 함수는 원문 전체를 그대로(세그먼트 필터링 없이) LLM에 보내고
    있었다 — "안심상속 조회 결과 예금 8천만 원, 아파트 5억 원, 카드대출
    2천만 원이 확인됐어요..."에서 LLM이 "카드대출"을 DisclosureItem
    화이트리스트(_VALID_ASSET_TYPES, 부채 유형이 아예 없음)에 맞는 유형이
    없다는 이유로 "기타"로 반환할 수 있었고, 같은 원문을 독립적으로 보는
    extract_liabilities()가 이미 "대출"로 정확히 잡은 항목이 자산에도
    중복 등록됐다(agent.py._merge_disclosures는 반환된 항목을 그대로
    다 반영하므로). extract_financial_slots()와 동일한 원칙 — 부채로
    식별되는 세그먼트는 이 LLM 호출 후보에서도 제외한다. 그 세그먼트는
    extract_liabilities()가 같은 원문을 독립적으로 재처리하므로 정보
    유실이 아니다.

    키가 없거나 호출이 실패하면 None을 돌려준다 — 호출부(agent.py)가
    이 신호를 보고 기존 extract_financial_slots() 일반 추출 경로로
    폴백해서, 사후 모드에서도 이 전용 파서가 못 잡는 문장을 조용히
    버리지 않는다."""
    segments = [s.strip() for s in _SEGMENT_SPLIT_RE.split(text) if s.strip()]
    disclosure_segments = [
        segment for segment in segments if _match_liability_type(segment) is None
    ]
    if not disclosure_segments:
        # 전부 부채로 식별되는 세그먼트였다 — 이 함수가 다룰 대상(자산
        # 조회 결과)이 없다. 성공적으로 아무것도 못 찾은 것과 동일하게
        # 빈 리스트를 돌려준다(None은 "LLM 자체를 못 씀"의 의미라 다름) —
        # 호출부는 disclosures가 빈 리스트든 뭐든 liability_missing과
        # 별개로 extract_liabilities()를 그대로 호출해 부채를 잡는다.
        return []
    filtered_text = " ".join(disclosure_segments)

    client = _client()
    if client is None:
        return None

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_DISCLOSURE_MAX_TOKENS,
            system=_build_disclosure_system_prompt(),
            messages=[{"role": "user", "content": filtered_text}],
            timeout=_TIMEOUT_SECONDS,
        )
        payload = _parse_json_response(response.content[0].text)
    except Exception:
        return None

    if payload is None:
        return None

    return _apply_disclosure_payload(payload)
