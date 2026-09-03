import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])';

/**
 * 접근성 대응 모달 컨테이너.
 * - role="dialog" + aria-modal + aria-labelledby
 * - 포커스 트랩, Escape 닫기, 열릴 때 첫 포커스, 닫힐 때 이전 포커스 복원
 * - variant: 데스크톱 center 카드 / 좁은 화면 bottom-sheet
 */
export function Dialog({
  title,
  onClose,
  children,
  variant = "center",
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  variant?: "center" | "sheet";
  footer?: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const prevFocus = useRef<HTMLElement | null>(null);
  const titleId = useRef(`dlg-${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    prevFocus.current = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    panel?.querySelector<HTMLElement>(FOCUSABLE)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKey, true);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = prevOverflow;
      prevFocus.current?.focus?.();
    };
  }, [onClose]);

  // body에 포탈로 붙인다 — 그렇지 않으면 backdrop-filter가 걸린 조상(다크 테마의
  // .app-header/.composer 등)이 position:fixed 오버레이의 containing block이
  // 돼버려서, 전체 화면이 아니라 그 조상 박스 안에만 작게 뜨는 문제가 생긴다.
  return createPortal(
    <div className={`dialog-overlay dialog-${variant}`} onMouseDown={onClose}>
      <div
        ref={panelRef}
        className="dialog-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId.current}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="dialog-header">
          <h2 id={titleId.current}>{title}</h2>
          <button type="button" className="dialog-close" onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>
        <div className="dialog-body">{children}</div>
        {footer && <div className="dialog-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
