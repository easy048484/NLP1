"""상속 절차 단계 정의.

절차는 선형 리스트가 아니라 선행조건 DAG입니다. 안심상속 원스톱(재산조회)은
사망신고와 별개로 진행할 수 있고, 한정승인/상속포기 3개월 시계는 재산조회
결과를 기다리는 동안에도 흐릅니다. 이 병렬성이 사용자가 가장 많이 다치는
지점이라 선형 모델로는 표현이 안 됩니다.

여기 있는 값(기한 개월 수, 근거 조문)은 이 에이전트가 내놓는 모든 숫자의
출처입니다. LLM은 이 값을 말로 풀어주기만 하고, 스스로 만들어내지 않습니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StepId(str, Enum):
    DEATH_REPORT = "death_report"  # 사망신고
    ONE_STOP = "one_stop"  # 안심상속 원스톱 서비스 신청
    ASSET_SEARCH = "asset_search"  # 상속재산 조회 결과 확인
    WILL_CHECK = "will_check"  # 유언장 존재 여부 확인
    ACCEPT_DECIDE = "accept_decide"  # 단순승인/한정승인/상속포기 결정
    DIVISION = "division"  # 상속재산분할협의
    REGISTRATION = "registration"  # 상속등기·명의이전
    ACQ_TAX = "acq_tax"  # 취득세 신고·납부
    INHERIT_TAX = "inherit_tax"  # 상속세 신고·납부


class DeadlineBase(str, Enum):
    """기한 기산의 기준점. 절차마다 다르다는 게 핵심."""

    DEATH = "death"  # 사망일(=사망 사실을 안 날로 갈음)
    KNOWN = "known"  # 상속개시 있음을 안 날 (민법 1019조)
    DEATH_MONTH_END = "death_month_end"  # 상속개시일이 속하는 달의 말일


@dataclass(frozen=True)
class Deadline:
    base: DeadlineBase
    months: int
    label: str
    law: str
    note: str = ""
    #: 팀에서 법령 원문 대조를 마쳤는지. False면 안내문에 검증 필요 표시가 붙습니다.
    verified: bool = True


@dataclass(frozen=True)
class Step:
    id: StepId
    title: str
    summary: str
    requires: tuple[StepId, ...] = ()
    deadline: Deadline | None = None
    #: 이 단계에서 다른 에이전트로 넘겨야 하면 그 에이전트 이름
    handoff: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)


STEPS: tuple[Step, ...] = (
    Step(
        id=StepId.DEATH_REPORT,
        title="사망신고",
        summary="주민센터에 사망 사실을 신고합니다. 이후 모든 절차의 전제가 됩니다.",
        deadline=Deadline(
            base=DeadlineBase.DEATH,
            months=1,
            label="사망신고 기한",
            law="가족관계의 등록 등에 관한 법률 제84조",
            note="기한을 넘기면 과태료가 부과될 수 있습니다.",
        ),
        aliases=("사망신고",),
    ),
    Step(
        id=StepId.ONE_STOP,
        title="안심상속 원스톱 서비스 신청",
        summary=(
            "사망자의 금융·토지·자동차·세금·연금 등을 한 번에 조회 신청합니다. "
            "사망신고와 동시에 신청할 수 있습니다."
        ),
        deadline=Deadline(
            base=DeadlineBase.DEATH_MONTH_END,
            months=6,
            label="안심상속 원스톱 신청 기한",
            law="사망자 등 재산조회 통합처리에 관한 기준(행정안전부)",
            note="기한이 지나도 기관별로 개별 조회는 가능하지만 통합 신청은 불가합니다.",
            verified=False,
        ),
        aliases=("안심상속", "원스톱", "재산조회 신청"),
    ),
    Step(
        id=StepId.ASSET_SEARCH,
        title="재산 조회 결과 확인",
        summary="기관별로 도착한 조회 결과로 상속재산과 채무의 규모를 파악합니다.",
        requires=(StepId.ONE_STOP,),
        handoff="tax_calculator",
        aliases=("재산조회", "조회결과", "잔액조회"),
    ),
    Step(
        id=StepId.WILL_CHECK,
        title="유언장 존재 여부 확인",
        summary="유언장이 있으면 분할 방식이 달라지므로 협의 전에 확인이 필요합니다.",
        handoff="decedent_estate",
        aliases=("유언장", "유언"),
    ),
    Step(
        id=StepId.ACCEPT_DECIDE,
        title="단순승인 / 한정승인 / 상속포기 결정",
        summary=(
            "상속을 그대로 받을지, 재산 범위 내에서만 빚을 갚을지, 아예 포기할지 "
            "정해서 가정법원에 신고합니다. 아무것도 하지 않으면 단순승인이 됩니다."
        ),
        deadline=Deadline(
            base=DeadlineBase.KNOWN,
            months=3,
            label="한정승인·상속포기 신고 기한",
            law="민법 제1019조 제1항",
            note=(
                "기산점이 사망일이 아니라 '상속개시 있음을 안 날'입니다. "
                "빚이 있는 줄 몰랐던 경우 특별한정승인(민법 제1019조 제3항)이 "
                "따로 있습니다."
            ),
        ),
        aliases=("한정승인", "상속포기", "포기", "승인"),
    ),
    Step(
        id=StepId.DIVISION,
        title="상속재산분할협의",
        summary=(
            "상속인 전원이 누가 무엇을 받을지 협의하고 협의서에 서명·날인합니다. "
            "한 명이라도 빠지면 협의서는 무효입니다."
        ),
        requires=(StepId.ACCEPT_DECIDE,),
        aliases=("분할협의", "협의서", "재산분할"),
    ),
    Step(
        id=StepId.REGISTRATION,
        title="상속등기·명의이전",
        summary="부동산은 등기소, 자동차는 차량등록사업소에서 명의를 넘깁니다.",
        requires=(StepId.DIVISION,),
        aliases=("등기", "명의이전", "소유권이전"),
    ),
    Step(
        id=StepId.ACQ_TAX,
        title="취득세 신고·납부",
        summary="상속받은 부동산·자동차에 대한 취득세를 시군구청에 신고·납부합니다.",
        requires=(StepId.DIVISION,),
        deadline=Deadline(
            base=DeadlineBase.DEATH_MONTH_END,
            months=6,
            label="상속 취득세 신고·납부 기한",
            law="지방세법 제20조 제1항",
            note="상속인 중 외국에 주소를 둔 사람이 있으면 9개월입니다.",
        ),
        aliases=("취득세",),
    ),
    Step(
        id=StepId.INHERIT_TAX,
        title="상속세 신고·납부",
        summary="관할 세무서에 상속세를 신고·납부합니다.",
        deadline=Deadline(
            base=DeadlineBase.DEATH_MONTH_END,
            months=6,
            label="상속세 신고·납부 기한",
            law="상속세 및 증여세법 제67조",
            note="피상속인이나 상속인 전원이 외국에 주소를 둔 경우 9개월입니다.",
        ),
        handoff="tax_calculator",
        aliases=("상속세", "세금신고"),
    ),
)

STEP_BY_ID: dict[StepId, Step] = {step.id: step for step in STEPS}

#: 사용자에게 보여줄 기본 순서. DAG이지만 화면에는 한 줄로 세워야 하므로
#: "보통 이 순서로 밟는다"는 표시 순서를 따로 둡니다.
DISPLAY_ORDER: tuple[StepId, ...] = tuple(step.id for step in STEPS)


def unlocked(completed: set[StepId]) -> list[Step]:
    """선행조건을 모두 만족했고 아직 끝내지 않은 단계들."""
    return [
        step
        for step in STEPS
        if step.id not in completed and all(req in completed for req in step.requires)
    ]


def blocked_by(step: Step, completed: set[StepId]) -> list[Step]:
    """이 단계를 막고 있는 선행 단계들."""
    return [STEP_BY_ID[req] for req in step.requires if req not in completed]
