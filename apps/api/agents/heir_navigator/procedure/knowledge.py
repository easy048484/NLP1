"""단계별 서류·접수기관 지식베이스.

RAG를 쓰지 않고 하드코딩합니다. 절차가 20개 미만이라 검색 정확도보다
"틀리면 바로 고칠 수 있고, 무엇이 검증됐는지 눈으로 확인된다"가 더 중요합니다.

각 항목의 last_verified / verified는 장식이 아닙니다. verified=False인 항목은
안내문에 "확인 필요" 표시가 자동으로 붙습니다. 팀에서 법령·기관 홈페이지
원문을 대조하고 나면 True로 올리고 날짜를 적어주세요.
"""

from __future__ import annotations

from dataclasses import dataclass

from .steps import StepId

TODO = "TODO"


@dataclass(frozen=True)
class StepGuide:
    step: StepId
    documents: tuple[str, ...]
    agencies: tuple[str, ...]
    links: tuple[tuple[str, str], ...] = ()
    tips: tuple[str, ...] = ()
    last_verified: str = TODO
    verified: bool = False


GUIDES: dict[StepId, StepGuide] = {
    StepId.DEATH_REPORT: StepGuide(
        step=StepId.DEATH_REPORT,
        documents=(
            "사망진단서 또는 사체검안서 원본",
            "신고인 신분증",
            "사망자의 가족관계를 확인할 수 있는 서류",
        ),
        agencies=("주소지 또는 사망지의 시·구·읍·면 사무소(주민센터)",),
        links=(("정부24", "https://www.gov.kr"),),
        tips=("사망신고를 하면서 안심상속 원스톱 서비스를 같이 신청할 수 있습니다.",),
    ),
    StepId.ONE_STOP: StepGuide(
        step=StepId.ONE_STOP,
        documents=(
            "신청인 신분증",
            "가족관계증명서(상세) 등 상속인임을 확인할 수 있는 서류",
        ),
        agencies=("주민센터 방문 신청", "정부24 온라인 신청"),
        links=(("정부24", "https://www.gov.kr"),),
        tips=(
            "금융거래·토지·자동차·국세·지방세·연금 가입 여부를 한 번에 조회 신청합니다.",
            "기관마다 결과 도착 시점이 달라 며칠에서 몇 주까지 걸릴 수 있습니다.",
        ),
    ),
    StepId.ASSET_SEARCH: StepGuide(
        step=StepId.ASSET_SEARCH,
        documents=("조회 결과 통지서 또는 각 기관 조회 화면",),
        agencies=("각 조회 기관(금융감독원, 국세청, 국토교통부 등)",),
        tips=(
            "조회 결과는 '계좌·채무의 존재 여부'이지 정확한 잔액이 아닌 경우가 많아, "
            "금액은 해당 금융기관에 별도로 확인해야 합니다.",
        ),
    ),
    StepId.WILL_CHECK: StepGuide(
        step=StepId.WILL_CHECK,
        documents=("유언장 원본 또는 공정증서 유언 사본",),
        agencies=(
            "공정증서 유언인 경우 작성 공증사무소",
            "자필 유언인 경우 가정법원(검인)",
        ),
        tips=("자필증서·비밀증서 유언은 가정법원의 검인 절차가 필요합니다.",),
    ),
    StepId.ACCEPT_DECIDE: StepGuide(
        step=StepId.ACCEPT_DECIDE,
        documents=(
            "상속포기 또는 한정승인 심판청구서",
            "사망자의 기본증명서·가족관계증명서·말소자 주민등록초본",
            "청구인의 가족관계증명서·주민등록등본",
            "인감증명서 또는 본인서명사실확인서",
            "(한정승인) 상속재산목록",
        ),
        agencies=("피상속인의 최후 주소지 관할 가정법원",),
        links=(("대한민국 법원 전자민원센터", "https://help.scourt.go.kr"),),
        tips=(
            "아무 신고도 하지 않고 기한이 지나면 단순승인한 것으로 보아 빚도 함께 상속됩니다.",
            "상속재산을 처분하면 단순승인한 것으로 볼 수 있어, 결정 전 재산 처분은 주의가 필요합니다.",
        ),
    ),
    StepId.DIVISION: StepGuide(
        step=StepId.DIVISION,
        documents=(
            "상속재산분할협의서",
            "상속인 전원의 인감증명서 및 인감 날인",
            "상속인 전원의 가족관계증명서",
        ),
        agencies=("별도 접수기관 없음(당사자 간 작성)",),
        tips=(
            "상속인 중 한 명이라도 빠지면 협의서 전체가 무효입니다.",
            "미성년 상속인과 그 친권자가 함께 상속인인 경우 특별대리인 선임이 필요할 수 있습니다.",
        ),
    ),
    StepId.REGISTRATION: StepGuide(
        step=StepId.REGISTRATION,
        documents=(
            "소유권이전등기 신청서",
            "상속재산분할협의서(협의로 나눈 경우)",
            "사망자 및 상속인 전원의 가족관계 서류",
            "취득세 납부 확인서",
            "토지·건축물대장 등본",
        ),
        agencies=(
            "부동산 소재지 관할 등기소",
            "자동차는 차량등록사업소",
        ),
        links=(("인터넷등기소", "https://www.iros.go.kr"),),
        tips=(
            "상속등기 자체에는 법정 기한이 없지만, 취득세 기한이 사실상 기준이 됩니다.",
        ),
    ),
    StepId.ACQ_TAX: StepGuide(
        step=StepId.ACQ_TAX,
        documents=("취득세 신고서", "상속재산분할협의서", "가족관계 서류"),
        agencies=("부동산 소재지 관할 시·군·구청 세무부서", "위택스 온라인 신고"),
        links=(("위택스", "https://www.wetax.go.kr"),),
    ),
    StepId.INHERIT_TAX: StepGuide(
        step=StepId.INHERIT_TAX,
        documents=(
            "상속세 과세표준 신고 및 자진납부계산서",
            "상속재산 명세 및 평가 자료",
            "채무·장례비 등 공제 증빙",
        ),
        agencies=("피상속인 주소지 관할 세무서", "홈택스 온라인 신고"),
        links=(("홈택스", "https://www.hometax.go.kr"),),
        tips=(
            "공제 후 낼 세금이 0원이어도 신고 자체는 해두는 편이 유리한 경우가 있습니다.",
        ),
    ),
}


def guide_for(step_id: StepId) -> StepGuide | None:
    return GUIDES.get(step_id)


def unverified_steps() -> list[StepId]:
    """아직 팀 검증이 끝나지 않은 단계 목록 (CI/리뷰용)."""
    return [step_id for step_id, guide in GUIDES.items() if not guide.verified]
