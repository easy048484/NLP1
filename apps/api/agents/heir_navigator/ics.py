"""기한을 캘린더(.ics) 파일로 변환.

Google Calendar API 대신 .ics를 고른 이유: OAuth 동의 흐름이 필요 없고,
아이폰·안드로이드 양쪽에서 그냥 열리고, 사망일·가족관계 같은 민감정보를
외부 서비스로 내보내지 않아도 됩니다. 서버에서 문자열로 만들면 끝입니다.
"""

from __future__ import annotations

from datetime import date, timedelta

from .procedure import DISCLAIMER, DeadlineItem

#: 며칠 전에 알림을 울릴지
REMINDER_DAYS = (30, 7, 1)


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """RFC 5545: 한 줄은 75옥텟까지. 넘으면 공백 한 칸으로 이어붙입니다."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks: list[bytes] = []
    while raw:
        # 멀티바이트 문자를 자르지 않도록 경계를 뒤로 물립니다.
        cut = 75 if not chunks else 74
        head, raw = raw[:cut], raw[cut:]
        while raw and (raw[0] & 0xC0) == 0x80:
            head, raw = head + raw[:1], raw[1:]
        chunks.append(head)
    return "\r\n ".join(chunk.decode("utf-8") for chunk in chunks)


def _event(item: DeadlineItem, *, session_id: str, stamp: str) -> list[str]:
    # 종일 일정. DTEND는 배타적이라 하루를 더합니다.
    start = item.due_date.strftime("%Y%m%d")
    end = (item.due_date + timedelta(days=1)).strftime("%Y%m%d")
    description = (
        f"{item.step_title} / 근거: {item.law}"
        + (f"\n{item.note}" if item.note else "")
        + f"\n기준: {item.base_label} {item.base_date.isoformat()}"
        + f"\n\n{DISCLAIMER}"
    )
    lines = [
        "BEGIN:VEVENT",
        f"UID:{item.step.value}-{session_id}@heir-navigator",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{start}",
        f"DTEND;VALUE=DATE:{end}",
        f"SUMMARY:[상속] {_escape(item.label)}",
        f"DESCRIPTION:{_escape(description)}",
        "TRANSP:TRANSPARENT",
    ]
    for days in REMINDER_DAYS:
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"TRIGGER:-P{days}D",
            f"DESCRIPTION:{_escape(item.label)} {days}일 전",
            "END:VALARM",
        ]
    lines.append("END:VEVENT")
    return lines


def build_calendar(
    deadlines: list[DeadlineItem],
    *,
    session_id: str = "session",
    now: date | None = None,
) -> str:
    """완료되지 않은 기한들을 하나의 .ics 문자열로 만듭니다."""
    pending = [item for item in deadlines if not item.completed]
    stamp = (now or date.today()).strftime("%Y%m%dT000000Z")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//family-assets//heir-navigator//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:상속 절차 기한",
    ]
    for item in pending:
        lines += _event(item, session_id=session_id, stamp=stamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
