/**
 * 긴 절차 안내 답변(heir_navigator 등)을 넘겨보는 카드로 쪼개거나, 여러
 * 확인 질문이 한 번에 몰린 답변을 체크리스트 카드로 바꾸기 위한 파서.
 * 둘 다 순수 텍스트 휴리스틱이다 — 백엔드 계약을 바꾸지 않고, 백엔드가
 * 실제로 이미 쓰고 있는 마크다운 패턴(## 섹션 제목, "- 라벨: 질문" 불릿)만
 * 인식한다. 패턴이 안 맞으면 null을 돌려주고, 호출부는 항상 기존처럼
 * 원문 마크다운을 그대로 보여주는 경로로 폴백한다.
 */

export interface ReplySection {
  title: string;
  body: string;
}

export interface ParsedReplySections {
  intro: string | null;
  sections: ReplySection[];
  /** 면책 고지 등 — 작은 글씨로 항상 노출 (평문 렌더 — ** 마커는 미리 걷어냄) */
  footer: string | null;
  /** 면책 고지 맨 앞에 "**...?**"로 붙어 오는 후속 질문만 따로 뽑아낸 것 —
   * 있으면 카드 바로 아래에 별도 후속질문 블록으로 보여준다. */
  footerQuestion: string | null;
}

/** 면책 고지 문단 맨 앞에 붙는 "**질문...?**" 문장만 후속질문으로 뽑아낸다.
 * 물음표로 끝나는 볼드 문장만 질문으로 취급 — 그 외의 볼드 문장(예:
 * "**위 정보는 검증 전입니다.**")은 그냥 고지 본문의 일부로 남긴다. */
const LEADING_BOLD_QUESTION = /^\*\*([^*]+?\?)\*\*\s*/;

function splitFooterQuestion(footer: string): { question: string | null; text: string | null } {
  const m = footer.match(LEADING_BOLD_QUESTION);
  if (!m) return { question: null, text: stripInlineMarkup(footer) || null };
  const question = stripInlineMarkup(m[1].trim());
  const text = stripInlineMarkup(footer.slice(m[0].length).trim());
  return { question, text: text || null };
}

/** 섹션 사이 구분선("---")을 앞뒤에서 잘라낸다 — 각 섹션 본문은 다음
 * "## " 제목 직전까지 슬라이스되므로 구분선이 꼬리에 그대로 남는다. */
function stripHr(s: string): string {
  return s.replace(/^\s*-{3,}\s*/, "").replace(/\s*-{3,}\s*$/, "").trim();
}

/** 카드 제목·라벨·질문처럼 <Markdown>이 아니라 일반 텍스트로 그대로
 * 렌더되는 짧은 필드에서 "**볼드**"/"__볼드__" 마커만 걷어낸다 — 안
 * 걷어내면 별표가 글자 그대로 화면에 노출된다. */
function stripInlineMarkup(s: string): string {
  return s.replace(/\*\*(.+?)\*\*/g, "$1").replace(/__(.+?)__/g, "$1");
}

/**
 * "## 제목" H2가 2개 이상이면 섹션 카드로 쪼갠다. 실제 답변은 섹션마다
 * "---"로 구분되어 있어(첫 섹션 앞에도 있을 수 있음) 헤더를 먼저 찾고 나서
 * 그 결과에서 구분선을 걷어내야 한다 — 반대 순서로 하면 첫 "---"에서
 * "안내 고지"를 찾는 로직이 뒤따르는 모든 섹션을 통째로 삼켜버린다.
 * 마지막 섹션 본문 끝에 "---"로 구분된 문단(면책 고지 등)이 남아 있으면
 * 카드 밖으로 빼서 항상 보이게 한다.
 */
export function parseReplySections(text: string): ParsedReplySections | null {
  const trimmed = text.trim();

  const headingRe = /^##\s+(.+)$/gm;
  const matches = [...trimmed.matchAll(headingRe)];
  if (matches.length < 2) return null;

  const firstIndex = matches[0].index ?? 0;
  const intro = stripHr(trimmed.slice(0, firstIndex)) || null;

  const sections: ReplySection[] = matches.map((m, i) => {
    const start = (m.index ?? 0) + m[0].length;
    const end =
      i + 1 < matches.length ? (matches[i + 1].index ?? trimmed.length) : trimmed.length;
    return {
      title: stripInlineMarkup(m[1].trim()),
      body: stripHr(trimmed.slice(start, end)),
    };
  });

  let footer: string | null = null;
  let footerQuestion: string | null = null;
  const last = sections[sections.length - 1];
  const footerMatch = last.body.match(/\n-{3,}\n+([\s\S]+)$/);
  if (footerMatch && footerMatch.index !== undefined) {
    last.body = last.body.slice(0, footerMatch.index).trim();
    const split = splitFooterQuestion(footerMatch[1].trim());
    footerQuestion = split.question;
    footer = split.text;
  }

  return { intro, sections, footer, footerQuestion };
}

export interface ConfirmChecklistItem {
  label: string;
  question: string;
}

export interface ParsedConfirmChecklist {
  intro: string;
  items: ConfirmChecklistItem[];
  rest: string | null;
}

/** decedent_estate가 "N가지만 직접 확인해주세요."로 여러 확인 질문을 한 번에
 * 몰아 물을 때 쓰는 고정 문구 — result_formatter.py의 _summary_pending()과
 * 정확히 같은 패턴이어야 한다. */
const CONFIRM_MARKER = /\*\*(?:[가-힣0-9]+가지|한\s*가지)만\s*직접\s*확인해주세요\.\*\*/;

/**
 * 위 문구가 있으면 바로 다음 문단의 "- 라벨: 질문" 불릿들을 항목별 카드로
 * 뽑아낸다. 마커가 없거나 다음 문단에서 불릿을 하나도 못 찾으면 null —
 * 호출부는 원래 마크다운 렌더링으로 폴백한다.
 */
export function parseConfirmChecklist(text: string): ParsedConfirmChecklist | null {
  if (!CONFIRM_MARKER.test(text)) return null;

  const paragraphs = text.trim().split(/\n\n+/);
  const introIndex = paragraphs.findIndex((p) => CONFIRM_MARKER.test(p));
  if (introIndex === -1) return null;

  const listParagraph = paragraphs[introIndex + 1] ?? "";
  const bulletRe = /^-\s+([^:：\n]+)[:：]\s*(.+)$/gm;
  const items: ConfirmChecklistItem[] = [];
  let m: RegExpExecArray | null;
  while ((m = bulletRe.exec(listParagraph))) {
    items.push({
      label: stripInlineMarkup(m[1].trim()),
      question: stripInlineMarkup(m[2].trim()),
    });
  }
  if (items.length === 0) return null;

  const rest = [...paragraphs.slice(0, introIndex), ...paragraphs.slice(introIndex + 2)]
    .join("\n\n")
    .trim();

  return { intro: paragraphs[introIndex].trim(), items, rest: rest || null };
}
