"""
금액 표기 변환 함수 단일화.

여러 곳(formatter, 슬롯 추출, 로그 등)에서 각자 포맷하지 않고
전부 이 함수를 거치도록 합니다. 포맷팅 로직이 흩어지면 한 곳만
고치고 다른 곳은 안 고쳐서 compose 단계의 verify_numbers 원문
대조가 깨질 수 있습니다 (decedent_estate에서 실제로 겪은 문제).
"""

from __future__ import annotations


def format_krw(amount: int) -> str:
    """
    원 단위 정수를 만/억 단위 한국어 표기로 변환. 만원 미만은 절삭.

    예: 30_000_000     -> "3,000만원"
        250_000_000    -> "2억 5,000만원"
        1_020_000_000  -> "10억 2,000만원"
        100_003_000    -> "1억"        (만원 미만 3,000원은 절삭)
        5_000          -> "5,000원"    (만원 미만 소액은 원 단위 그대로)
        0              -> "0원"
    """
    negative = amount < 0
    amount = abs(amount)

    eok, rest = divmod(amount, 100_000_000)
    man = rest // 10_000

    if eok == 0 and man == 0:
        text = f"{amount:,}원"
    else:
        parts = []
        if eok:
            parts.append(f"{eok}억")
        if man:
            parts.append(f"{man:,}만원")
        text = " ".join(parts)

    return f"-{text}" if negative else text
