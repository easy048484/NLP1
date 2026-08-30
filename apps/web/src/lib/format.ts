/** 금액·날짜 표시 공통 포맷터. */

const WON = new Intl.NumberFormat("ko-KR");

/** 1234567 → "123만 4,567원" (한국식 만/억 단위 병기). */
export function formatWon(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return "—";
  const neg = amount < 0;
  const abs = Math.abs(Math.round(amount));
  if (abs === 0) return "0원";

  const eok = Math.floor(abs / 100_000_000);
  const man = Math.floor((abs % 100_000_000) / 10_000);
  const rest = abs % 10_000;

  const parts: string[] = [];
  if (eok > 0) parts.push(`${WON.format(eok)}억`);
  if (man > 0) parts.push(`${WON.format(man)}만`);
  if (rest > 0 || parts.length === 0) parts.push(`${WON.format(rest)}`);
  return `${neg ? "-" : ""}${parts.join(" ")}원`;
}

/** 정확한 원 단위 (내역 테이블용): "1,234,567원". */
export function formatWonExact(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return "—";
  return `${WON.format(Math.round(amount))}원`;
}

/** ISO date("2026-05-03") → "2026년 5월 3일". */
export function formatDateKo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일`;
}

/** 남은 일수 계산 (오늘 기준, 음수면 지남). */
export function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  d.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / 86_400_000);
}

/** Blob 다운로드를 트리거 (.ics 등). 뷰어 샌드박스가 아닌 실제 앱에서만 동작. */
export function downloadText(filename: string, content: string, mime = "text/calendar"): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
