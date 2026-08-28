"""가족관계 파생 계산 (담당: 지원).

법정상속분(배우자 1.5 : 자녀 1) 계산은 한때 이 모듈에 있었으나, 런타임
호출처가 없고 tax_calculator.calculate_spouse_legal_share가 실제 사용처라
제거했습니다. 단일화(tax가 family_graph를 호출)는 승원님과 협의 후 후속 PR로
다룹니다.
"""
