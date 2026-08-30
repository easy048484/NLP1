"""현행 민법을 바탕으로 한 유류분 MVP 규칙과 고지 문구."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

from .models import ComplexityFlag

RULE_VERSION = "civil_act_2026-03-17"
RULE_EFFECTIVE_FROM = date(2026, 3, 17)

LEGAL_SOURCES = [
    "민법 제1009조(법정상속분)",
    "민법 제1112조(유류분의 권리자와 유류분)",
    "민법 제1113조(유류분의 산정)",
    "민법 제1114조(산입될 증여)",
    "민법 제1115조(유류분의 보전)",
]

LEGAL_SOURCE_URLS = [
    "https://www.law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1030472287",
    "https://www.law.go.kr/lsLinkCommonInfo.do?lsJoLnkSeq=1031182201",
    "https://www.law.go.kr/LSW/lsLinkCommonInfo.do?lsJoLnkSeq=1032404379",
    "https://www.law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1026990849",
    "https://law.go.kr/LSW/lsLinkCommonInfo.do?lsJoLnkSeq=1031985365",
]

FORCED_SHARE_RATES: dict[str, Fraction] = {
    "spouse": Fraction(1, 2),
    "child": Fraction(1, 2),
    "parent": Fraction(1, 3),
    # 2024. 9. 20. 개정으로 형제자매 유류분 조항은 삭제됐다.
    "sibling": Fraction(0, 1),
}

COMPLEXITY_LABELS: dict[ComplexityFlag, str] = {
    ComplexityFlag.PRIOR_GIFT: "과거 증여의 산입 범위 또는 수증자별 내역 확인 필요",
    ComplexityFlag.SPECIAL_BENEFIT: "특별수익 적용 여부 확인 필요",
    ComplexityFlag.CONTRIBUTION_SHARE: "기여분 주장 또는 인정 여부 확인 필요",
    ComplexityFlag.RENUNCIATION_OR_DISQUALIFICATION: (
        "상속포기·상속결격·상속권 상실 여부 확인 필요"
    ),
    ComplexityFlag.REPRESENTATION_INHERITANCE: "대습상속 관계와 지분 확인 필요",
    ComplexityFlag.VALUATION_DISPUTE: "재산가액 평가 또는 감정 필요",
    ComplexityFlag.FOREIGN_ELEMENT: "해외 재산·외국 거주 등 국제 요소 확인 필요",
    ComplexityFlag.USER_REPORTED_COMPLEX_CASE: (
        "사용자가 복잡한 상속 사정이 있다고 답변함"
    ),
}

DOCUMENTS_TO_PREPARE = [
    "가족관계증명서·기본증명서 등 가족관계 확인 자료",
    "유언장 또는 재산분배 계획서",
    "부동산·예금·주식·보험 등 재산 내역",
    "대출·임대차보증금 반환채무 등 채무 자료",
    "사전증여가 있다면 증여계약서·이체내역·증여세 신고자료",
    "상속포기·분할협의·기여분 등 관련 자료(해당하는 경우)",
]
