import type { ReactNode } from "react";

/**
 * verify_numbers 실패 시. 색만으로 구분 금지 → ⚠ 아이콘 + 문장.
 */
export function NeedsReviewBadge() {
  return (
    <div className="needs-review" role="note">
      <span aria-hidden="true" className="needs-review-icon">
        ⚠
      </span>
      <span>이 답변의 숫자는 각 항목 원문을 확인해 주세요.</span>
    </div>
  );
}


/**
 * compose 가 LLM 합성 없이 각 에이전트 원문을 이어붙였을 때(verification.mode
 * === "concat"). 숫자는 원문 그대로라 안전하지만, 한 편의 답변으로 다듬어지지
 * 않았음을 알린다 — LLM 미사용 환경(키 없음/플래그 off)이 조용히 지나가지 않게.
 */
export function ConcatNoticeBadge() {
  return (
    <div className="needs-review" role="note">
      <span aria-hidden="true" className="needs-review-icon">
        ⚡
      </span>
      <span>간이 응답 — 에이전트별 답변을 합성 없이 그대로 나열했습니다.</span>
    </div>
  );
}

/** 법률·세무 자문이 아님을 알리는 고지. 전역 하단 고정 + 카드 인라인 두 변형. */
export function Disclaimer({
  children,
  variant = "inline",
}: {
  children?: ReactNode;
  variant?: "inline" | "global";
}) {
  return (
    <p className={`disclaimer disclaimer-${variant}`}>
      {children ??
        "이 서비스는 법률·세무 자문이 아니며, 유언장 원문을 저장하지 않습니다."}
    </p>
  );
}

/** 골드 헤어라인. 워드마크·섹션 제목 아래. */
export function GoldRule() {
  return <span className="gold-rule" aria-hidden="true" />;
}

/** 아이브로/키커 (대문자, 자간 넓게, 골드). */
export function Eyebrow({ children }: { children: ReactNode }) {
  return <span className="eyebrow">{children}</span>;
}
