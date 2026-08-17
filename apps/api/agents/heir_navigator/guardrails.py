"""경계(하지 않는 것)를 코드로 강제합니다.

프롬프트에 "추천하지 마세요"라고만 써두면 서너 턴 뒤에 샙니다. 두 겹으로 막습니다.

1) 입력 감지: 금지 주제가 감지되면 LLM을 아예 태우지 않고 고정 템플릿을 돌려줌
2) 출력 후검사: 생성된 답변에 추천/단정 패턴이 있으면 폴백으로 교체

여기 걸리는 건 "답을 못 한다"가 아니라 "다른 방식으로 답한다"입니다.
선택지와 각각의 결과는 사실대로 전부 제공합니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Boundary(str, Enum):
    #: 한정승인/상속포기 중 무엇을 고를지 판단·추천 요구
    CHOICE_RECOMMENDATION = "choice_recommendation"
    #: 누가 얼마를 가질지 등 구체적 재산 배분 개입 요구
    DIVISION_INTERVENTION = "division_intervention"
    #: 가족 간 상속 갈등의 중재자 역할 요구
    FAMILY_CONFLICT = "family_conflict"


@dataclass(frozen=True)
class GuardrailHit:
    boundary: Boundary
    matched: str
    reply: str
    next_action: str | None = None


# 판단·추천을 요구하는 표현. "한정승인이 뭐예요?" 같은 설명 요청은 걸리지 않도록
# 선택 요구 신호(뭐가 나아 / 어떻게 해야 / 추천 / 골라)를 반드시 함께 봅니다.
_CHOICE_TOPIC = re.compile(r"한정승인|상속\s*포기|단순승인|포기할|승인할")
_CHOICE_ASK = re.compile(
    r"뭐가?\s*(나|더|좋|유리|낫)|어느\s*(쪽|것)|어떤\s*걸|어떻게\s*해야"
    r"|추천|골라|선택해\s*줘|정해\s*줘|하는\s*게\s*맞|해야\s*하나|해야\s*할까"
)

_DIVISION_ASK = re.compile(
    r"얼마씩|얼마나\s*(받|가져)|누가\s*(더|많이)|공평하게\s*나|어떻게\s*나눠"
    r"|배분|분배\s*(해|방안|안)|몫을\s*정"
)

_CONFLICT_ASK = re.compile(
    r"싸우|다투|분쟁|안\s*준다|안\s*주려|연락\s*(안|두절)|도장\s*안|서명\s*안"
    r"|우기|억울|사기\s*친|가로채|편들|누가\s*잘못"
)

_CHOICE_REPLY = """어떤 쪽을 선택해야 하는지는 안내드릴 수 없습니다. 재산과 빚의 규모, 각자의 사정에 따라 결과가 크게 달라지고 법적 책임이 따르는 결정이라, 대신 판단하면 오히려 손해를 드릴 수 있어서입니다.

대신 세 가지 선택지와 각각의 결과를 사실대로 정리해 드립니다.

**단순승인** — 재산과 빚을 모두 그대로 물려받습니다. 아무 신고도 하지 않고 기한(상속개시를 안 날부터 3개월)이 지나면 자동으로 이렇게 됩니다. 빚이 재산보다 많으면 상속인이 본인 재산으로 갚아야 합니다.

**한정승인** — 물려받은 재산 범위 안에서만 빚을 갚습니다. 재산을 넘는 빚은 갚지 않아도 됩니다. 가정법원에 상속재산목록을 붙여 신고해야 하고, 이후 채권자에게 알리고 청산하는 절차가 따라옵니다.

**상속포기** — 재산도 빚도 받지 않습니다. 다만 내가 포기하면 상속권이 다음 순위(자녀 → 손자녀 → 부모 → 형제자매 등)로 넘어가서, 가족 중 다른 사람이 빚을 떠안게 될 수 있습니다. 이 점 때문에 가족이 함께 검토하는 경우가 많습니다.

세 선택 모두 기한은 상속개시 있음을 안 날부터 3개월입니다(민법 제1019조 제1항).

구체적인 상황에 어떤 선택이 맞는지는 법률구조공단(국번없이 132) 또는 변호사 상담을 이용해 주세요."""

_DIVISION_REPLY = """누가 얼마를 가질지는 제가 정해 드릴 수 없습니다. 구체적인 재산 배분은 상속인들의 합의 사항이고, 제가 개입하면 특정인에게 불리한 결과가 될 수 있어서입니다.

대신 절차에 대한 사실 정보는 드릴 수 있습니다.

- 상속인 전원이 합의하면 법정상속분과 다르게 나눠도 됩니다.
- 협의서에는 상속인 **전원**의 서명·날인과 인감증명서가 필요합니다. 한 명이라도 빠지면 협의서 전체가 무효입니다.
- 합의가 되지 않으면 가정법원의 상속재산분할 조정·심판 절차가 있습니다.

법정상속분이 얼마인지, 협의에 누구의 동의가 필요한지는 알려드릴 수 있으니 물어봐 주세요."""

_CONFLICT_REPLY = """가족 간의 일에는 제가 어느 편도 들 수 없습니다. 사정을 다 알지 못한 채 한쪽 이야기만 듣고 판단하면 도움이 되지 않아서입니다.

절차상 사실만 말씀드리면,

- 상속재산분할협의는 상속인 전원의 동의가 있어야 성립합니다. 협의가 되지 않으면 가정법원에 **상속재산분할 조정**을 신청할 수 있고, 조정이 안 되면 **심판**으로 넘어갑니다.
- 조정·심판은 피상속인의 최후 주소지 관할 가정법원에 신청합니다.
- 한정승인·상속포기 3개월 기한은 협의가 진행 중이어도 멈추지 않습니다. 기한 관리는 따로 챙기셔야 합니다.

상담이 필요하시면 대한법률구조공단(국번없이 132)이나 가까운 가정법원 가사상담실을 이용하실 수 있습니다."""

_REPLIES = {
    Boundary.CHOICE_RECOMMENDATION: _CHOICE_REPLY,
    Boundary.DIVISION_INTERVENTION: _DIVISION_REPLY,
    Boundary.FAMILY_CONFLICT: _CONFLICT_REPLY,
}


def check_input(message: str) -> GuardrailHit | None:
    """사용자 발화가 경계를 건드리는지 검사합니다.

    resolve(절차 계산)보다 **앞**에서 돌아야 합니다. "한정승인이랑 포기 중에
    뭐가 나아요?"는 절차 계산이 필요 없이 바로 고정 응답으로 빠져야 합니다.
    """
    text = message or ""
    if _CHOICE_TOPIC.search(text) and _CHOICE_ASK.search(text):
        return _hit(Boundary.CHOICE_RECOMMENDATION, text)
    if _DIVISION_ASK.search(text):
        return _hit(Boundary.DIVISION_INTERVENTION, text)
    if _CONFLICT_ASK.search(text):
        return _hit(Boundary.FAMILY_CONFLICT, text)
    return None


def _hit(boundary: Boundary, matched: str) -> GuardrailHit:
    return GuardrailHit(
        boundary=boundary, matched=matched[:120], reply=_REPLIES[boundary]
    )


# 출력 후검사: 모델이 어쨌든 추천을 해버린 경우를 잡습니다.
_OUTPUT_RECOMMEND = re.compile(
    r"(한정승인|상속\s*포기|단순승인)[^.\n]{0,40}"
    r"(추천|권해|권장|하시는\s*게\s*좋|하는\s*것이\s*좋|유리합니다|나으십니다)"
)
_OUTPUT_CERTAIN = re.compile(r"확정적으로|틀림없이|반드시\s*\S+됩니다|100%")


def check_output(reply: str) -> Boundary | None:
    """생성된 답변이 경계를 넘었는지 검사. 넘었으면 폴백으로 교체합니다."""
    if _OUTPUT_RECOMMEND.search(reply or ""):
        return Boundary.CHOICE_RECOMMENDATION
    return None


def has_overclaim(reply: str) -> bool:
    """기한 등을 법적 확정으로 단정하는 표현이 있는지."""
    return bool(_OUTPUT_CERTAIN.search(reply or ""))


def fallback_reply(boundary: Boundary) -> str:
    return _REPLIES[boundary]
