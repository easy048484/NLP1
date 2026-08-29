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
- 예외적으로 InsuranceTag만 금액 없이도(value=0, note="금액 미언급") 생성한다.
  보험은 애초에 "노후 재원 계산에서 제외"되는 태그라(engine.py가 아예 보지
  않음) 0을 넣어도 시뮬레이션 결과가 조용히 틀려질 위험이 없다. 반면 Asset
  의 value는 engine.simulate()의 잔액 계산에 직접 들어가므로, 유형만 알고
  금액을 모르면 Asset을 만들지 않고 missing으로만 남긴다.
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
_LiabilityLabel = Literal["대출", "카드론", "전세자금대출"]

_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT_SECONDS = 8.0
_MAX_TOKENS = 400

_SYSTEM_PROMPT = (
    "너는 사용자의 자연어 발화에서 금융자산·소득·보험 정보를 추출하는 도구다.\n"
    "정규식으로 못 잡은 표현만 너에게 온다. 절대 판정하거나 조언하지 마라 — "
    "너는 오직 값 추출만 한다.\n"
    "금액이나 나이를 확실히 알 수 없으면 절대 숫자를 지어내지 마라 — 그 항목은 "
    "생략하고 unclear 배열에 이유를 적어라.\n"
    "반드시 아래 JSON 형식으로만 답하라. 코드블록이나 다른 설명을 절대 덧붙이지 "
    "마라.\n"
    "{\n"
    '  "assets": [{"type": "예금|주식|펀드|부동산|기타", "value": 원단위 정수}],\n'
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


_NOISE_RE = re.compile(r"정도|쯤|가량|약|한(?=\s*\d)")
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
    "만": 10_000,
    "원": 1,
}
_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(조|억|천만|백만|천|만|원)")


def _parse_amount(text: str) -> Optional[int]:
    """텍스트에서 원화 금액을 찾아 정수(원)로 돌려준다. 못 찾으면 None —
    절대 0으로 대체하지 않는다 (호출부가 missing 처리 여부를 결정)."""
    cleaned = _NOISE_RE.sub("", text)
    matches = _UNIT_RE.findall(cleaned)
    if not matches:
        return None
    total = Decimal("0")
    for number, unit in matches:
        total += Decimal(number) * _UNIT_MULTIPLIERS[unit]
    return int(total)


_ASSET_KEYWORDS: dict[AssetType, tuple[str, ...]] = {
    "예금": ("예금", "적금", "저금"),
    "주식": ("주식",),
    "펀드": ("펀드",),
    "부동산": ("집", "아파트", "주택", "부동산", "건물"),
}
_INSURANCE_KEYWORDS = ("보험",)
# 마침표는 소수점과 구분해야 해서 숫자 사이 마침표는 분리 대상에서 뺀다("3.5억" 보존).
# "있고"는 콤마 없이 자산·부채를 나열할 때 흔한 연결어("예금 1억 있고 대출
# 3천만원 있어요") — 안 자르면 한 세그먼트에 숫자가 두 개 이상 섞여
# _parse_amount가 둘을 합산해버리는 실측 버그가 있었다.
_SEGMENT_SPLIT_RE = re.compile(r"(?<!\d)[.](?!\d)|[,、]|그리고|또한|있고")


def _match_asset_type(segment: str) -> Optional[AssetType]:
    for asset_type, keywords in _ASSET_KEYWORDS.items():
        if any(keyword in segment for keyword in keywords):
            return asset_type
    return None


def _regex_extract(text: str) -> tuple[ExtractionResult, list[str]]:
    """정규식 1차 파싱. (지금까지 확정된 결과, 정규식이 유형조차 못 알아본
    세그먼트 목록)을 함께 돌려준다 — 후자는 LLM 폴백 대상이 된다."""
    segments = [s.strip() for s in _SEGMENT_SPLIT_RE.split(text) if s.strip()]

    assets: list[Asset] = []
    insurance_tags: list[InsuranceTag] = []
    missing: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for segment in segments:
        if any(keyword in segment for keyword in _INSURANCE_KEYWORDS):
            amount = _parse_amount(segment)
            insurance_tags.append(
                InsuranceTag(
                    type="보험",
                    value=amount if amount is not None else 0,
                    note=None if amount is not None else "금액 미언급",
                )
            )
            continue

        asset_type = _match_asset_type(segment)
        if asset_type is None:
            unresolved.append(segment)
            continue

        amount = _parse_amount(segment)
        if amount is None:
            # 유형은 확인됐지만 금액이 없다. Asset.value는 engine.simulate()의
            # 잔액 계산에 직접 쓰이므로, InsuranceTag와 달리 값을 지어내면
            # 시뮬레이션 결과가 조용히 틀려진다 — 그래서 Asset을 만들지 않고
            # 후속 질문 대상으로만 남긴다.
            missing.append(
                {
                    "kind": "asset_value",
                    "asset_type": asset_type,
                    "segment": segment,
                    "reason": f"{asset_type} 금액이 언급되지 않음",
                }
            )
            continue

        assets.append(Asset(type=asset_type, value=amount))

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
}


def _match_liability_type(segment: str) -> Optional[_LiabilityLabel]:
    for liability_type, keywords in _LIABILITY_KEYWORDS.items():
        if any(keyword in segment for keyword in keywords):
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
            system=_SYSTEM_PROMPT,
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
        insurance_tags.append(
            InsuranceTag(
                type="보험",
                value=int(value) if has_value else 0,
                note=None if has_value else "금액 미언급",
            )
        )

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

    llm_payload = _llm_extract(text)
    if llm_payload is None:
        for segment in unresolved:
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
_IMAGE_SYSTEM_PROMPT = (
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
    '  "assets": [{"type": "예금|주식|펀드|부동산|기타", "value": 원단위 정수}],\n'
    '  "liabilities": [{"type": "대출|카드론|전세자금대출|기타", '
    '"remaining_balance": 원단위 정수}],\n'
    '  "insurance": [{"value": 원단위 정수 또는 null}],\n'
    '  "unclear": ["무엇을 확인하지 못했는지에 대한 짧은 설명(개인정보 제외)"]\n'
    "}"
)

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
#: 프롬프트가 이 4개만 쓰라고 지시하지만, 모델이 그 지시를 무시하고
#: "국민은행 대출(계좌 110-xxx, 홍길동)"처럼 계좌번호·이름이 섞인 문자열을
#: 채워 보내는 경우를 대비해 여기서 한 번 더 막는다(수집 최소화 원칙,
#: 4-6절) — 화이트리스트 밖 값은 원문(오염 가능성 있는 문자열)만 버리고
#: "기타"로 대체한다. 항목 자체를 통째로 드롭하면 실제 부채가 사용자
#: 재무 상태에서 사라져 순자산이 실제보다 좋아 보이게 왜곡된다 — PII를
#:막으려다 반대 방향으로 더 위험한 실수를 하는 셈이라, "기타"(이미 검증된
#: 정상 카테고리라 새로 추측하는 게 아님)로 보존한다.
_VALID_LIABILITY_TYPES = ("대출", "카드론", "전세자금대출", "기타")


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
            system=_IMAGE_SYSTEM_PROMPT,
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
