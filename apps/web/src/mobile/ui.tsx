/**
 * 모바일 간단 버전 공용 화면 부품.
 * 원칙: 모든 화면은 하단 고정 주 버튼(CTA) 하나로 끝난다 — 막다른 화면 없음.
 */
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { agentMeta } from "../lib/agents";
import { Markdown } from "../lib/markdown";
import type { ConsultAxis } from "../types";
import { askAgent, HEIR_COLORS, type Family } from "./lib";

// ------------------------------------------------------------------ 셸

export function MobileShell({
  title,
  onBack,
  step,
  total,
  children,
  cta,
  secondary,
  tone = "page",
}: {
  title: string;
  onBack?: () => void;
  step?: number;
  total?: number;
  children: ReactNode;
  cta?: ReactNode;
  secondary?: ReactNode;
  tone?: "page" | "warm";
}) {
  const navigate = useNavigate();
  return (
    <div className={`m-app m-tone-${tone}`}>
      <header className="m-top">
        <button
          type="button"
          className="m-icon-btn"
          aria-label="뒤로"
          onClick={onBack ?? (() => navigate(-1))}
        >
          <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
            <path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
        <h1 className="m-top-title">{title}</h1>
        <button
          type="button"
          className="m-icon-btn"
          aria-label="처음 화면"
          onClick={() => navigate("/m")}
        >
          <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
            <path
              d="M4 11l8-7 8 7v9h-5v-6H9v6H4z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </header>

      {step !== undefined && total !== undefined && (
        <div className="m-progress" aria-label={`${total}단계 중 ${step}단계`}>
          <div className="m-progress-bar">
            <span style={{ width: `${(step / total) * 100}%` }} />
          </div>
          <div className="m-progress-count">
            <b>{step}</b> / {total}
          </div>
        </div>
      )}

      <main className="m-body">{children}</main>

      {(cta || secondary) && (
        <footer className="m-cta-bar">
          {secondary}
          {cta}
        </footer>
      )}
    </div>
  );
}

export function Cta({
  children,
  onClick,
  disabled,
  variant = "primary",
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  variant?: "primary" | "ghost";
}) {
  return (
    <button
      type="button"
      className={`m-cta m-cta-${variant}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

export function Heading({ eyebrow, title }: { eyebrow?: string; title: ReactNode }) {
  return (
    <div className="m-heading">
      {eyebrow && <p className="m-eyebrow">{eyebrow}</p>}
      <h2 className="m-title">{title}</h2>
    </div>
  );
}

// ------------------------------------------------------------------ 입력

export function ChoiceButtons<T extends string | number | boolean>({
  options,
  value,
  onSelect,
  disabled,
  columns = 1,
}: {
  options: { label: string; value: T; hint?: string }[];
  value?: T | null;
  onSelect: (value: T) => void;
  disabled?: boolean;
  columns?: 1 | 2 | 3;
}) {
  return (
    <div className={`m-choices m-cols-${columns}`}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          className={`m-choice${value === o.value ? " is-on" : ""}`}
          aria-pressed={value === o.value}
          disabled={disabled}
          onClick={() => onSelect(o.value)}
        >
          <span>{o.label}</span>
          {o.hint && <small>{o.hint}</small>}
        </button>
      ))}
    </div>
  );
}

const QUICK_AMOUNTS = [
  { label: "+1천만", value: 10_000_000 },
  { label: "+1억", value: 100_000_000 },
  { label: "+5억", value: 500_000_000 },
];

export function AmountField({
  label,
  help,
  value,
  onChange,
}: {
  label: string;
  help?: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const [focused, setFocused] = useState(false);
  const shown = value ? new Intl.NumberFormat("ko-KR").format(value) : "";
  return (
    <div className="m-amount">
      <label className="m-amount-label">
        {label}
        <div className={`m-amount-input${focused ? " is-focus" : ""}`}>
          <input
            inputMode="numeric"
            value={shown}
            placeholder="0"
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onChange={(e) => {
              const digits = e.target.value.replace(/[^\d]/g, "");
              onChange(digits ? Math.min(Number(digits), 1e14) : 0);
            }}
          />
          <span>원</span>
        </div>
      </label>
      <div className="m-quick">
        {QUICK_AMOUNTS.map((q) => (
          <button key={q.label} type="button" onClick={() => onChange(value + q.value)}>
            {q.label}
          </button>
        ))}
        <button type="button" onClick={() => onChange(0)}>
          지우기
        </button>
      </div>
      {help && <p className="m-help">{help}</p>}
    </div>
  );
}

export function Counter({
  value,
  onChange,
  min = 0,
  max = 6,
  unit = "명",
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  unit?: string;
}) {
  return (
    <div className="m-counter">
      <button
        type="button"
        aria-label="줄이기"
        disabled={value <= min}
        onClick={() => onChange(value - 1)}
      >
        −
      </button>
      <output>
        {value}
        <small>{unit}</small>
      </output>
      <button
        type="button"
        aria-label="늘리기"
        disabled={value >= max}
        onClick={() => onChange(value + 1)}
      >
        +
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ 에이전트

/** "○○ 에이전트가 확인했어요" + 원문 답변 펼쳐보기. */
export function AgentNote({
  agent,
  summary,
  reply,
}: {
  agent: string;
  summary: string;
  reply?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const meta = agentMeta(agent);
  return (
    <div className="m-agent-note" style={{ borderColor: `var(${meta.colorVar})` }}>
      <div className="m-agent-note-head">
        <span
          className="m-agent-dot"
          style={{ background: `var(${meta.bgVar})`, color: `var(${meta.colorVar})` }}
          aria-hidden="true"
        >
          {meta.emoji}
        </span>
        <div>
          <p className="m-agent-name">{meta.shortLabel} 에이전트</p>
          <p className="m-agent-summary">{summary}</p>
        </div>
      </div>
      {reply && (
        <>
          <button
            type="button"
            className="m-link-btn"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "설명 접기" : "에이전트 설명 전체 보기"}
          </button>
          {open && (
            <div className="m-agent-reply">
              <Markdown>{reply}</Markdown>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function Thinking({ agent, text }: { agent: string; text: string }) {
  const meta = agentMeta(agent);
  return (
    <div className="m-thinking" role="status" aria-live="polite">
      <span className="m-agent-dot m-pulse" aria-hidden="true" style={{ background: `var(${meta.bgVar})` }}>
        {meta.emoji}
      </span>
      <p>
        <b>{meta.shortLabel} 에이전트</b>가 {text}
      </p>
      <p className="m-help">조금 걸릴 수 있어요. 화면을 닫아도 입력한 내용은 저장돼요.</p>
    </div>
  );
}

export function ErrorBox({
  message,
  onRetry,
  onLater,
}: {
  message: string;
  onRetry: () => void;
  onLater?: () => void;
}) {
  return (
    <div className="m-error" role="alert">
      <p>{message}</p>
      <div className="m-row">
        <button type="button" className="m-chip" onClick={onRetry}>
          다시 시도
        </button>
        {onLater && (
          <button type="button" className="m-chip" onClick={onLater}>
            나중에 이어하기
          </button>
        )}
      </div>
    </div>
  );
}

/** "에이전트에게 더 묻기" 칩 → 바텀시트에 답변. 같은 세션이라 앞선 결과를 알고 답한다. */
export function AskChips({
  sessionId,
  axis,
  family,
  questions,
  title = "에이전트에게 더 물어보기",
}: {
  sessionId: string;
  axis: ConsultAxis;
  family?: Family | null;
  questions: string[];
  title?: string;
}) {
  const [sheet, setSheet] = useState<{
    q: string;
    loading: boolean;
    reply?: string;
    agent?: string;
    error?: string;
  } | null>(null);

  async function ask(q: string) {
    setSheet({ q, loading: true });
    const { response, error } = await askAgent(sessionId, q, { axis, family });
    setSheet({
      q,
      loading: false,
      reply: response?.reply,
      agent: response?.primary_agent ?? response?.agents[0],
      error: error ?? undefined,
    });
  }

  return (
    <section className="m-card">
      <h3 className="m-card-title">{title}</h3>
      <div className="m-chip-wrap">
        {questions.map((q) => (
          <button key={q} type="button" className="m-chip" onClick={() => void ask(q)}>
            {q}
          </button>
        ))}
      </div>
      {sheet && (
        <div className="m-sheet-backdrop" onClick={() => !sheet.loading && setSheet(null)}>
          <div
            className="m-sheet"
            role="dialog"
            aria-modal="true"
            aria-label={sheet.q}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="m-sheet-grip" aria-hidden="true" />
            <p className="m-sheet-q">{sheet.q}</p>
            {sheet.loading && <Thinking agent="heir_navigator" text="답을 찾고 있어요…" />}
            {sheet.error && <ErrorBox message={sheet.error} onRetry={() => void ask(sheet.q)} />}
            {sheet.reply && (
              <>
                {sheet.agent && (
                  <p className="m-agent-name">{agentMeta(sheet.agent).shortLabel} 에이전트의 답변</p>
                )}
                <div className="m-agent-reply">
                  <Markdown>{sheet.reply}</Markdown>
                </div>
              </>
            )}
            <button
              type="button"
              className="m-cta m-cta-primary"
              disabled={sheet.loading}
              onClick={() => setSheet(null)}
            >
              확인하고 계속하기
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ 이어지는 카드

export function NextCard({
  eyebrow,
  title,
  onClick,
  tone = "plain",
}: {
  eyebrow?: string;
  title: string;
  onClick: () => void;
  tone?: "plain" | "gold" | "navy";
}) {
  return (
    <button type="button" className={`m-next m-next-${tone}`} onClick={onClick}>
      <span>
        {eyebrow && <small>{eyebrow}</small>}
        {title}
      </span>
      <span aria-hidden="true" className="m-next-arrow">
        ›
      </span>
    </button>
  );
}

// ------------------------------------------------------------------ 차트

/** 도넛 차트 — 조각 사이 간격, 가운데 라벨. 색은 토큰만. */
export function Donut({
  parts,
  label,
}: {
  parts: { name: string; value: number; color: string }[];
  label: string;
}) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  const r = 70;
  const c = 2 * Math.PI * r;
  const gap = parts.length > 1 ? 4 : 0;
  let offset = 0;
  return (
    <figure className="m-donut">
      <svg viewBox="0 0 200 200" role="img" aria-label={parts.map((p) => `${p.name} ${Math.round((p.value / total) * 100)}%`).join(", ")}>
        <g transform="rotate(-90 100 100)">
          {parts.map((p) => {
            const len = (p.value / total) * c;
            const el = (
              <circle
                key={p.name}
                cx="100"
                cy="100"
                r={r}
                fill="none"
                stroke={p.color}
                strokeWidth="34"
                strokeDasharray={`${Math.max(0, len - gap)} ${c}`}
                strokeDashoffset={-offset}
              />
            );
            offset += len;
            return el;
          })}
        </g>
        <text x="100" y="106" textAnchor="middle" className="m-donut-label">
          {label}
        </text>
      </svg>
      <figcaption className="m-legend">
        {parts.map((p) => (
          <span key={p.name}>
            <i style={{ background: p.color }} aria-hidden="true" />
            {p.name} ({Math.round((p.value / total) * 100)}%)
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

export function Avatar({ name, index }: { name: string; index: number }) {
  return (
    <span className="m-avatar" style={{ borderColor: HEIR_COLORS[index % HEIR_COLORS.length] }} aria-hidden="true">
      {name === "배우자" ? "💑" : "🧑"}
      <i style={{ background: HEIR_COLORS[index % HEIR_COLORS.length] }} />
    </span>
  );
}
