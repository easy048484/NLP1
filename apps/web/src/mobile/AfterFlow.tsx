/**
 * /m/after — 20~50대 자녀용 "가족이 떠나신 뒤": 사망 후 절차 안내 + 유언장 점검.
 * 누가·언제 → 버튼 문답(heir_navigator pending_questions) → 할 일·기한 → 유언장(decedent_estate)
 */
import { useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { parsePendingQuestions, parseSignals } from "../lib/agentData";
import { SignalRow } from "../components/ui";
import type { ChatResponse, PendingQuestion, RequirementSignal } from "../types";
import {
  AFTER_KEY,
  askAgent,
  contributionOf,
  dateKo,
  downloadText,
  todayIso,
  useFlowState,
  type Family,
} from "./lib";
import {
  AgentNote,
  AskChips,
  ChoiceButtons,
  Counter,
  Cta,
  ErrorBox,
  Heading,
  MobileShell,
  NextCard,
  Thinking,
} from "./ui";

type AfterStep = "start" | "check" | "plan" | "will";

interface Deadline {
  step: string;
  step_title: string;
  label: string;
  due_date: string;
  days_left: number;
  law?: string;
  note?: string;
  completed?: boolean;
}
interface NextAction {
  step: string;
  title: string;
  summary: string;
  documents?: string[];
  agencies?: string[];
  links?: { label: string; url: string }[];
  tips?: string[];
  deadline?: Deadline | null;
}
interface TimelineEntry {
  step: string;
  title: string;
  summary: string;
  status: "done" | "ready" | "blocked" | string;
}
interface Plan {
  deadlines?: Deadline[];
  urgent?: Deadline[];
  overdue?: Deadline[];
  next_actions?: NextAction[];
  timeline?: TimelineEntry[];
  solvency?: { debt_exceeds_assets?: boolean; note?: string } | null;
}

interface AfterState {
  sessionId: string;
  step: AfterStep;
  relation: string;
  deathDate: string;
  family: Family;
  plan: Plan | null;
  ics: string | null;
  navReply: string | null;
  question: PendingQuestion | null;
  answered: string[];
  will: {
    reply: string;
    questions: PendingQuestion[];
    signals: RequirementSignal[];
    willType: string | null;
    noWill: boolean;
  } | null;
}

const initial = (): Omit<AfterState, "sessionId"> => ({
  step: "start",
  relation: "아버지",
  deathDate: todayIso(-1),
  family: { spouse: true, children: 2 },
  plan: null,
  ics: null,
  navReply: null,
  question: null,
  answered: [],
  will: null,
});

/** heir_navigator 가 되묻는 슬롯 — 에이전트가 이번 턴에 질문을 안 줘도 흐름이 끊기지 않게 같은 선택지를 준비해 둔다. */
const FALLBACK_QUESTIONS: PendingQuestion[] = [
  {
    requirement: "progress",
    field: "",
    question: "지금까지 **어디까지 진행하셨나요?**",
    options: ["아직 아무것도 못 했어요", "사망신고는 했어요", "안심상속 원스톱까지 신청했어요", "재산 조회 결과까지 받았어요"].map(
      (t) => ({ label: t, value: t }),
    ),
  },
  {
    requirement: "has_debt",
    field: "",
    question: "재산 조회 결과에 **빚(대출·카드값 등)**이 있었나요?",
    options: ["빚이 있었어요", "빚은 없었어요", "아직 몰라요"].map((t) => ({ label: t, value: t })),
  },
  {
    requirement: "will_exists",
    field: "",
    question: "**유언장이 있는지** 확인되셨나요?",
    options: ["유언장이 있어요", "유언장이 없어요", "아직 몰라요"].map((t) => ({ label: t, value: t })),
  },
  {
    requirement: "agreement",
    field: "",
    question: "다른 가족과 **재산을 어떻게 나눌지** 이야기가 진행 중인가요?",
    options: ["아직 시작 전이에요", "협의를 진행 중이에요"].map((t) => ({ label: t, value: t })),
  },
];

/** "했어요" 버튼이 보낼 문장 — heir_navigator 규칙 파서가 완료로 인식하는 표현. */
const DONE_PHRASE: Record<string, string> = {
  death_report: "사망신고는 했어요",
  one_stop: "안심상속 원스톱 신청했어요",
  asset_search: "재산 조회 결과 받았어요",
  will_check: "유언장이 없어요",
  accept_decide: "한정승인·상속포기 여부를 결정해 신고했어요",
  division: "분할 협의서 작성했어요",
  registration: "상속 등기 했어요",
  acq_tax: "취득세 신고했어요",
  inherit_tax: "상속세 신고했어요",
};

const RELATIONS = ["아버지", "어머니", "배우자", "형제·자매", "그 외 가족"];

function dday(days: number): string {
  if (days < 0) return `D+${-days}`;
  if (days === 0) return "D-DAY";
  return `D-${days}`;
}

export function AfterFlow() {
  const params = useParams();
  const navigate = useNavigate();
  const [s, update, reset] = useFlowState<AfterState>(AFTER_KEY, initial);
  const step = (params.step as AfterStep) ?? s.step;
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ msg: string; retry: () => void } | null>(null);
  const [willText, setWillText] = useState("");
  const [openAction, setOpenAction] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function go(next: AfterStep) {
    update({ step: next });
    navigate(`/m/after/${next}`);
    window.scrollTo(0, 0);
  }

  function nextFallback(answered: string[]): PendingQuestion | null {
    return FALLBACK_QUESTIONS.find((q) => !answered.includes(q.requirement)) ?? null;
  }

  /** 아직 답하지 않은 질문 — 에이전트가 준 질문 우선, 없으면 준비해 둔 순서대로. */
  function openQuestion(): PendingQuestion | null {
    if (s.question && !s.answered.includes(s.question.requirement)) return s.question;
    return nextFallback(s.answered);
  }

  /** 응답을 읽어 상태를 갱신하고, 다음 화면을 정한다. */
  function absorb(response: ChatResponse, answered: string[], from: AfterStep): void {
    const nav = contributionOf(response, "heir_navigator");
    const est = contributionOf(response, "decedent_estate");
    const patch: Partial<AfterState> = { answered };

    if (nav) {
      const plan = nav.data.plan as Plan | undefined;
      if (plan) patch.plan = plan;
      if (typeof nav.data.calendar_ics === "string") patch.ics = nav.data.calendar_ics;
      patch.navReply = nav.reply;
      const q = parsePendingQuestions(nav.data, nav.agent)?.[0] ?? null;
      patch.question = q && !answered.includes(q.requirement) ? q : nextFallback(answered);
    }

    if (est) {
      const ws = response.will_status;
      patch.will = {
        reply: est.reply,
        questions: parsePendingQuestions(est.data, est.agent) ?? [],
        signals: parseSignals(est.data, est.agent) ?? [],
        willType: ws?.will_type ?? null,
        noWill: ws?.no_will ?? false,
      };
      update(patch);
      if (patch.will.noWill) go("plan");
      else if (from !== "will") go("will");
      return;
    }

    update(patch);
    if (from === "start") go("check");
    else if (from === "check" && !patch.question) go("plan");
  }

  async function call(
    message: string,
    opts: { context?: Record<string, unknown>; image?: { base64: string; mediaType: string } },
    answered: string[],
    from: AfterStep,
    label: string,
  ) {
    setBusy(label);
    setError(null);
    const { response, error: err } = await askAgent(s.sessionId, message, {
      axis: "post_death",
      family: s.family,
      ...opts,
    });
    setBusy(null);
    if (err || !response) {
      setError({ msg: err ?? "다시 시도해주세요.", retry: () => void call(message, opts, answered, from, label) });
      return;
    }
    absorb(response, answered, from);
  }

  function start() {
    const who = s.relation === "그 외 가족" ? "가족" : s.relation;
    void call(
      `${who}께서 ${s.deathDate}에 돌아가셨어요. 어떤 절차를 밟아야 하나요?`,
      {},
      [],
      "start",
      "절차와 기한을 정리하고 있어요…",
    );
  }

  function answer(q: PendingQuestion, opt: { label: string; value: string }, from: AfterStep) {
    const answered = q.requirement && !s.answered.includes(q.requirement) ? [...s.answered, q.requirement] : s.answered;
    void call(
      opt.label,
      q.field ? { context: { [q.field]: opt.value } } : {},
      answered,
      from,
      "답을 반영하고 있어요…",
    );
  }

  function skip() {
    const q = openQuestion();
    if (!q) return go("plan");
    const answered = [...s.answered, q.requirement];
    const next = nextFallback(answered);
    update({ answered, question: next });
    if (!next) go("plan");
  }

  // ---------------------------------------------------------------- 1. 누가·언제

  if (step === "start") {
    return (
      <MobileShell
        title="사망 후 절차 안내"
        onBack={() => navigate("/m")}
        step={1}
        total={3}
        cta={
          <Cta onClick={start} disabled={!!busy || !s.deathDate}>
            {busy ? "정리하는 중…" : "해야 할 일 안내 받기"}
          </Cta>
        }
      >
        <Heading eyebrow="마음이 무거우실 때, 순서대로 도와드릴게요" title="누가 언제 떠나셨나요?" />
        <section className="m-card">
          <h3 className="m-card-title">돌아가신 분</h3>
          <ChoiceButtons
            columns={3}
            value={s.relation}
            options={RELATIONS.map((r) => ({ label: r, value: r }))}
            onSelect={(v) => update({ relation: v })}
          />
        </section>
        <section className="m-card">
          <h3 className="m-card-title">돌아가신 날짜</h3>
          <div className="m-chip-wrap">
            {[
              { label: "오늘", v: todayIso(0) },
              { label: "어제", v: todayIso(-1) },
              { label: "일주일 전", v: todayIso(-7) },
            ].map((d) => (
              <button
                key={d.label}
                type="button"
                className={`m-chip${s.deathDate === d.v ? " is-on" : ""}`}
                onClick={() => update({ deathDate: d.v })}
              >
                {d.label}
              </button>
            ))}
          </div>
          <input
            type="date"
            className="m-date"
            max={todayIso(0)}
            value={s.deathDate}
            aria-label="돌아가신 날짜 직접 선택"
            onChange={(e) => update({ deathDate: e.target.value })}
          />
          <p className="m-help">대부분의 기한이 이 날짜부터 계산돼요.</p>
        </section>
        <section className="m-card">
          <h3 className="m-card-title">남은 가족 (상속인)</h3>
          <p className="m-label">고인의 배우자</p>
          <ChoiceButtons
            columns={2}
            value={s.family.spouse}
            options={[
              { label: "계세요", value: true },
              { label: "안 계세요", value: false },
            ]}
            onSelect={(v) => update({ family: { ...s.family, spouse: v } })}
          />
          <p className="m-label">고인의 자녀 수 (본인 포함)</p>
          <Counter value={s.family.children} onChange={(v) => update({ family: { ...s.family, children: v } })} />
        </section>
        {busy && <Thinking agent="heir_navigator" text={busy} />}
        {error && <ErrorBox message={error.msg} onRetry={error.retry} />}
      </MobileShell>
    );
  }

  const plan = s.plan;
  const deadlines = (plan?.deadlines ?? []).filter((d) => !d.completed);
  const actions = plan?.next_actions ?? [];
  const first = actions[0];

  // ---------------------------------------------------------------- 2. 버튼 문답

  if (step === "check") {
    const q = openQuestion();
    const idx = FALLBACK_QUESTIONS.findIndex((f) => f.requirement === q?.requirement);
    const urgent = plan?.urgent?.[0] ?? deadlines[0];
    return (
      <MobileShell
        title="사망 후 절차 안내"
        onBack={() => go("start")}
        step={2}
        total={3}
        cta={<Cta variant="ghost" onClick={() => go("plan")}>질문은 그만, 할 일 바로 보기</Cta>}
      >
        {urgent && (
          <div className="m-dday-strip">
            <b>{dday(urgent.days_left)}</b>
            <span>
              {urgent.label} · {dateKo(urgent.due_date)}까지
            </span>
          </div>
        )}
        {q ? (
          <>
            <Heading
              eyebrow={`더 정확한 안내를 위해 ${idx >= 0 ? `${idx + 1}/${FALLBACK_QUESTIONS.length}` : ""}`}
              title={q.question.split("\n")[0].replace(/\*\*/g, "")}
            />
            <ChoiceButtons
              disabled={!!busy}
              options={q.options}
              onSelect={(v) => {
                const opt = q.options.find((o) => o.value === v)!;
                answer(q, opt, "check");
              }}
            />
            <button type="button" className="m-link-btn m-center" onClick={skip} disabled={!!busy}>
              잘 모르겠어요 · 건너뛰기
            </button>
          </>
        ) : (
          <Heading eyebrow="확인 끝" title="이제 해야 할 일을 정리해드릴게요" />
        )}
        {busy && <Thinking agent="heir_navigator" text={busy} />}
        {error && <ErrorBox message={error.msg} onRetry={error.retry} />}
      </MobileShell>
    );
  }

  // ---------------------------------------------------------------- 4. 유언장 점검

  if (step === "will") {
    const w = s.will;
    const wq = w?.questions[0];
    const needsContent = !!w && !wq && w.signals.length === 0 && !w.noWill && !!w.willType;
    const hasRed = w?.signals.some((x) => x.grade === "red") ?? false;
    const doneChecking = !!w && !wq && w.signals.length > 0;
    return (
      <MobileShell
        title="유언장 점검"
        onBack={() => go("plan")}
        cta={
          !w ? (
            <Cta
              disabled={!!busy}
              onClick={() => void call("유언장이 있어요", {}, [...s.answered, "will_exists"], "will", "유언장 점검을 준비하고 있어요…")}
            >
              유언장 점검 시작하기
            </Cta>
          ) : (
            <Cta variant={doneChecking ? "primary" : "ghost"} onClick={() => go("plan")}>
              {doneChecking ? "절차 안내로 돌아가기" : "나중에 하고 할 일 보기"}
            </Cta>
          )
        }
      >
        <Heading eyebrow="유언장이 있으면 나누는 방식이 달라져요" title="유언장이 법적으로 효력이 있을까요?" />
        {w && wq && (
          <section className="m-card">
            <h3 className="m-card-title">{wq.question}</h3>
            <ChoiceButtons
              disabled={!!busy}
              options={wq.options}
              onSelect={(v) => {
                const opt = wq.options.find((o) => o.value === v)!;
                answer(wq, opt, "will");
              }}
            />
            {w.questions.length > 1 && <p className="m-help">남은 확인 {w.questions.length - 1}개</p>}
          </section>
        )}
        {needsContent && (
          <section className="m-card">
            <h3 className="m-card-title">유언장 내용을 보여주세요</h3>
            <p className="m-help">사진은 판독 직후 폐기되고 저장되지 않아요.</p>
            <button type="button" className="m-choice" onClick={() => fileRef.current?.click()} disabled={!!busy}>
              <span>📷 유언장 사진 올리기</span>
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                const reader = new FileReader();
                reader.onload = () => {
                  const base64 = String(reader.result).split(",")[1] ?? "";
                  void call("유언장 사진이에요", { image: { base64, mediaType: f.type || "image/jpeg" } }, s.answered, "will", "유언장을 읽고 있어요…");
                };
                reader.readAsDataURL(f);
                e.target.value = "";
              }}
            />
            <p className="m-label">또는 적힌 내용을 그대로 입력</p>
            <textarea
              className="m-textarea"
              rows={4}
              value={willText}
              placeholder="예: 나 홍길동은 … 2025년 3월 1일 서울 강남구 … 홍길동 (인)"
              onChange={(e) => setWillText(e.target.value)}
            />
            <button
              type="button"
              className="m-chip m-chip-strong"
              disabled={!willText.trim() || !!busy}
              onClick={() => void call(`유언장 내용: ${willText.trim()}`, {}, s.answered, "will", "요건을 하나씩 확인하고 있어요…")}
            >
              이 내용으로 점검하기
            </button>
          </section>
        )}
        {w && w.signals.length > 0 && (
          <section className="m-card">
            <h3 className="m-card-title">요건 신호등</h3>
            {w.signals.map((sig) => (
              <SignalRow key={sig.id} signal={sig} />
            ))}
          </section>
        )}
        {w && (
          <AgentNote
            agent="decedent_estate"
            summary={
              doneChecking
                ? hasRed
                  ? "확인되지 않은 요건이 있어요. 효력 다툼이 생길 수 있어 전문가 확인을 권해요."
                  : "형식 요건을 확인했어요. 신호등의 주의 항목만 살펴보세요."
                : "몇 가지만 확인하면 형식 요건을 판단해드릴게요."
            }
            reply={w.reply}
          />
        )}
        {doneChecking && hasRed && (
          <NextCard eyebrow="효력이 걱정된다면" title="전문가 상담이 필요해요 · PC 상담에서 이어하기" tone="gold" onClick={() => navigate("/chat")} />
        )}
        {busy && <Thinking agent="decedent_estate" text={busy} />}
        {error && <ErrorBox message={error.msg} onRetry={error.retry} />}
      </MobileShell>
    );
  }

  // ---------------------------------------------------------------- 3. 할 일·기한

  const remainingQ = openQuestion();
  const willUnknown = !s.will && !s.answered.includes("will_exists");
  return (
    <MobileShell
      title="해야 할 일"
      onBack={() => go("check")}
      step={3}
      total={3}
      cta={
        first ? (
          <Cta
            disabled={!!busy}
            onClick={() =>
              void call(DONE_PHRASE[first.step] ?? `${first.title} 했어요`, {}, s.answered, "plan", "다음 할 일을 정리하고 있어요…")
            }
          >
            {busy ? "정리하는 중…" : "✓ 이 일을 마쳤어요 · 다음 할 일"}
          </Cta>
        ) : (
          <Cta onClick={() => navigate("/m/prepare")}>나의 상속도 미리 준비해보기</Cta>
        )
      }
    >
      {busy && <Thinking agent="heir_navigator" text={busy} />}
      {error && <ErrorBox message={error.msg} onRetry={error.retry} onLater={() => navigate("/m")} />}
      {plan?.solvency?.debt_exceeds_assets && (
        <div className="m-alert">⚠ 빚이 재산보다 많을 수 있어요. 상속포기·한정승인 기한을 꼭 확인하세요.</div>
      )}

      {first && (
        <section className="m-card m-card-focus">
          <p className="m-eyebrow">지금 가장 먼저 할 일</p>
          <div className="m-focus-head">
            <h2 className="m-card-h">{first.title}</h2>
            {first.deadline && <span className="m-dday">{dday(first.deadline.days_left)}</span>}
          </div>
          <p>{first.summary}</p>
          {first.deadline && <p className="m-help">{dateKo(first.deadline.due_date)}까지 · {first.deadline.law}</p>}
          <ActionDetail action={first} />
        </section>
      )}

      {deadlines.length > 0 && (
        <section className="m-card">
          <h3 className="m-card-title">놓치면 안 되는 기한</h3>
          {deadlines.map((d) => (
            <div key={d.label} className={`m-deadline${d.days_left <= 14 ? " is-urgent" : ""}`}>
              <b>{dday(d.days_left)}</b>
              <span>
                {d.label}
                <small>{dateKo(d.due_date)}</small>
              </span>
            </div>
          ))}
          {s.ics && (
            <button type="button" className="m-outline-btn" onClick={() => downloadText("eznext-상속기한.ics", s.ics!, "text/calendar")}>
              📅 기한을 내 캘린더에 저장
            </button>
          )}
        </section>
      )}

      {actions.length > 1 && (
        <section className="m-card">
          <h3 className="m-card-title">그다음 할 일</h3>
          {actions.slice(1).map((a) => (
            <div key={a.step} className="m-acc">
              <button type="button" className="m-acc-head" aria-expanded={openAction === a.step} onClick={() => setOpenAction(openAction === a.step ? null : a.step)}>
                <span>{a.title}</span>
                {a.deadline && <small>{dday(a.deadline.days_left)}</small>}
              </button>
              {openAction === a.step && (
                <div className="m-acc-body">
                  <p>{a.summary}</p>
                  <ActionDetail action={a} />
                </div>
              )}
            </div>
          ))}
        </section>
      )}

      {plan?.timeline && plan.timeline.length > 0 && (
        <section className="m-card">
          <h3 className="m-card-title">전체 진행 순서</h3>
          <ol className="m-timeline">
            {plan.timeline.map((t) => (
              <li key={t.step} className={`is-${t.status}`}>
                <span aria-hidden="true">{t.status === "done" ? "✓" : t.status === "ready" ? "●" : "○"}</span>
                {t.title}
                <small>{t.status === "done" ? "완료" : t.status === "ready" ? "지금 가능" : "앞 단계 후"}</small>
              </li>
            ))}
          </ol>
        </section>
      )}

      {s.navReply && <AgentNote agent="heir_navigator" summary="진행 상황에 맞춰 순서와 기한을 정리했어요." reply={s.navReply} />}

      <h3 className="m-section-label">다음으로 해볼 일</h3>
      {remainingQ && (
        <NextCard eyebrow="몇 가지만 더 알려주시면 더 정확해요" title={remainingQ.question.split("\n")[0].replace(/\*\*/g, "")} tone="gold" onClick={() => { update({ question: remainingQ }); go("check"); }} />
      )}
      {willUnknown || (s.will && !s.will.noWill) ? (
        <NextCard
          eyebrow={s.will?.signals.length ? "점검한 유언장" : "유언장이 있다면"}
          title={s.will?.signals.length ? "유언장 요건 신호등 다시 보기" : "유언장 효력 점검하기"}
          onClick={() => go("will")}
        />
      ) : null}
      <AskChips
        sessionId={s.sessionId}
        axis="post_death"
        family={s.family}
        questions={["사망신고는 어디서 해요?", "안심상속 원스톱이 뭐예요?", "빚이 더 많으면 어떻게 해요?"]}
      />
      <NextCard eyebrow="나와 부모님을 위해" title="우리 가족 상속, 미리 준비해보기" tone="navy" onClick={() => navigate("/m/prepare")} />
      <button type="button" className="m-link-btn m-center" onClick={() => { reset(); navigate("/m/after/start"); }}>
        처음부터 다시 하기
      </button>
    </MobileShell>
  );
}

function ActionDetail({ action }: { action: NextAction }) {
  return (
    <div className="m-action-detail">
      {!!action.documents?.length && (
        <>
          <p className="m-label">가져갈 것</p>
          <ul>
            {action.documents.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </>
      )}
      {!!action.agencies?.length && (
        <>
          <p className="m-label">어디로</p>
          <ul>
            {action.agencies.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </>
      )}
      {!!action.tips?.length && <p className="m-note">💡 {action.tips[0]}</p>}
      {!!action.links?.length && (
        <div className="m-chip-wrap">
          {action.links.map((l) => (
            <a key={l.url} className="m-chip" href={l.url} target="_blank" rel="noreferrer">
              {l.label} 바로가기 ↗
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
