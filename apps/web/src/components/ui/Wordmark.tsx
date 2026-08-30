/** EZNEXT 워드마크. size로 로그인 hero / 헤더 두 용도를 커버. */
export function Wordmark({
  size = "md",
  showTagline = false,
}: {
  size?: "sm" | "md" | "lg";
  showTagline?: boolean;
}) {
  return (
    <span className={`wordmark wordmark-${size}`}>
      <span className="wordmark-mark" aria-hidden="true">
        <svg viewBox="0 0 64 64" width="1em" height="1em">
          <rect width="64" height="64" rx="14" fill="var(--brand-navy)" />
          <path
            d="M18 20 L30 32 L18 44"
            fill="none"
            stroke="var(--ink-inverse)"
            strokeWidth="6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M34 20 L46 32 L34 44"
            fill="none"
            stroke="var(--brand-gold)"
            strokeWidth="6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      <span className="wordmark-text">
        EZNEXT<span className="sr-only"> — 이지넥스트</span>
      </span>
      {showTagline && (
        <span className="wordmark-tagline">가족의 다음을 쉽게 설계하다</span>
      )}
    </span>
  );
}
