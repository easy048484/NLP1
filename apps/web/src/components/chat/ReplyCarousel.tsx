import { useState } from "react";
import { Markdown } from "../../lib/markdown";
import type { ReplySection } from "../../lib/replySections";

/**
 * 절차 안내처럼 "## 섹션" 여러 개로 나뉜 긴 답변을 한 화면에 다 펼치지 않고
 * 카드 한 장씩 넘겨보게 한다. 좌측 체크리스트·일정 패널과 내용이 겹치더라도
 * (같은 절차를 다른 형태로 보여주는 것) 여기서는 손대지 않는다 — 이 카드는
 * "왜/근거"를, 패널은 "무엇을/언제"를 담당하는 것으로 역할을 나눈다.
 */
export function ReplyCarousel({
  intro,
  sections,
  footer,
}: {
  intro: string | null;
  sections: ReplySection[];
  footer: string | null;
}) {
  const [index, setIndex] = useState(0);
  const total = sections.length;
  const section = sections[index];
  const atStart = index === 0;
  const atEnd = index === total - 1;

  return (
    <div className="reply-carousel">
      {intro && (
        <div className="reply-carousel-intro">
          <Markdown>{intro}</Markdown>
        </div>
      )}

      <div className="reply-carousel-card">
        <div className="reply-carousel-head">
          <button
            type="button"
            className="reply-carousel-nav"
            aria-label="이전 항목"
            disabled={atStart}
            onClick={() => setIndex((v) => Math.max(0, v - 1))}
          >
            ‹
          </button>
          <div className="reply-carousel-title-wrap">
            <span className="reply-carousel-count">
              {index + 1} / {total}
            </span>
            <h3 className="reply-carousel-title">{section.title}</h3>
          </div>
          <button
            type="button"
            className="reply-carousel-nav"
            aria-label="다음 항목"
            disabled={atEnd}
            onClick={() => setIndex((v) => Math.min(total - 1, v + 1))}
          >
            ›
          </button>
        </div>

        <div className="reply-carousel-body">
          <Markdown>{section.body}</Markdown>
        </div>

        <div className="reply-carousel-dots" role="tablist" aria-label="섹션 목록">
          {sections.map((s, i) => (
            <button
              key={`${s.title}-${i}`}
              type="button"
              role="tab"
              className={`reply-carousel-dot${i === index ? " on" : ""}`}
              aria-selected={i === index}
              aria-label={s.title}
              onClick={() => setIndex(i)}
            />
          ))}
        </div>
      </div>

      {footer && <p className="reply-carousel-footer">{footer}</p>}
    </div>
  );
}
