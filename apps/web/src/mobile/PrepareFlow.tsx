/**
 * /m/prepare — 부모님용 "미리 준비하기": 상속설계 + 상속세 미리보기.
 * 자산 → 가족 → 나눌 비율 → 유류분 신호등(heir_share_analyzer) → 결과 → 상속세(tax_calculator)
 */
import { useState, type CSSProperties } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { parseShares, parseShareWarnings, parseTaxResult, type ShareRow } from "../lib/agentData";
import type { TaxResult } from "../types";
import {
  agentField,
  askAgent,
  contributionOf,
  HEIR_COLORS,
  heirNames,
  percentsToAmounts,
  PREPARE_KEY,
  rebalancePercents,
  statutoryPercents,
  useFlowState,
  won,
  wonShort,
  type Family,
} from "./lib";
import {
  AgentNote,
  AmountField,
  AskChips,
  Avatar,
  ChoiceButtons,
  Counter,
  Cta,
  Donut,
  ErrorBox,
  Heading,
  MobileShell,
  NextCard,
  Thinking,
} from "./ui";

export type PrepareStep = "assets" | "family" | "shares" | "check" | "result" | "tax";

interface PrepareState {
  sessionId: string;
  step: PrepareStep;
  financial: number;
  other: number;
  debts: number;
  family: Family;
  percents: Record<string, number>;
  share: { rows: ShareRow[]; warnings: string[]; reply: string } | null;
  tax: { result: TaxResult; reply: string } | null;
}

const initial = (): Omit<PrepareState, "sessionId"> => ({
  step: "assets",
  financial: 0,
  other: 0,
  debts: 0,
  family: { spouse: true, children: 2 },
  percents: {},
  share: null,
  tax: null,
});

const FINANCIAL_TYPES = new Set(["예금", "적금", "주식", "펀드", "채권", "현금", "퇴직연금", "연금", "보험", "가상자산"]);

const TOTAL_STEPS = 4;

export function PrepareFlow() {
  const params = useParams();
  const navigate = useNavigate();
  const [s, update, reset] = useFlowState<PrepareState>(PREPARE_KEY, initial);
  const step = (params.step as PrepareStep) ?? s.step;
  const [busy, setBusy] = useState<null | "asset" | "share" | "tax">(null);
  const [error, setError] = useState<string | null>(null);
  const [assetText, setAssetText] = useState("");
  const [assetNote, setAssetNote] = useState<string | null>(null);

  const estate = s.financial + s.other;
  const names = heirNames(s.family);
  const percentTotal = names.reduce((a, n) => a + (s.percents[n] ?? 0), 0);
  const amounts = percentsToAmounts(
    Object.fromEntries(names.map((n) => [n, s.percents[n] ?? 0])),
    Math.round((estate * percentTotal) / 100),
  );

  function go(next: PrepareStep) {
    setError(null);
    update({ step: next });
    navigate(`/m/prepare/${next}`);
    window.scrollTo(0, 0);
  }

  // ---------------------------------------------------------------- 에이전트 호출

  async function organizeAssets() {
    if (!assetText.trim()) return;
    setBusy("asset");
    setError(null);
    const { response, error: err } = await askAgent(
      s.sessionId,
      `내 재산 정리해줘. ${assetText.trim()}`,
      { axis: "pre_need" },
    );
    setBusy(null);
    if (err || !response) return setError(err);
    const out = contributionOf(response, "asset_organizer");
    const assets = (agentField(out, "assets") as { type?: string; value?: number }[]) ?? [];
    const liabilities =
      (agentField(out, "liabilities") as { remaining_balance?: number }[]) ?? [];
    if (!assets.length && !liabilities.length) {
      setAssetNote("금액을 찾지 못했어요. '아파트 5억, 예금 3천만'처럼 적어주세요.");
      return;
    }
    let financial = 0;
    let other = 0;
    for (const a of assets) {
      const v = typeof a.value === "number" ? a.value : 0;
      if (FINANCIAL_TYPES.has(a.type ?? "")) financial += v;
      else other += v;
    }
    const debts = liabilities.reduce(
      (acc, l) => acc + (typeof l.remaining_balance === "number" ? l.remaining_balance : 0),
      0,
    );
    update({ financial, other, debts, share: null, tax: null });
    setAssetNote("자산정리 에이전트가 채워드렸어요. 금액이 맞는지 확인하고 고쳐주세요.");
  }

  async function checkShares() {
    setBusy("share");
    setError(null);
    const planned = percentsToAmounts(
      Object.fromEntries(names.map((n) => [n, s.percents[n] ?? 0])),
      estate,
    );
    const { response, error: err } = await askAgent(s.sessionId, "유류분 점검해줘", {
      axis: "pre_need",
      family: s.family,
      context: {
        share_input: {
          stage: "pre_death",
          estate_value: estate,
          debts: s.debts,
          planned_acquisitions: planned,
          complexity_flags: [],
        },
      },
    });
    setBusy(null);
    if (err || !response) return setError(err);
    const out = contributionOf(response, "heir_share_analyzer");
    const rows = out ? parseShares(out.data, out.agent) : null;
    if (!out || !rows) {
      setError(
        "유류분 분석 에이전트가 이 가족 구성은 간단 계산이 어렵다고 했어요. 가족 구성을 확인하거나 전문가 확인이 필요해요.",
      );
      return;
    }
    update({
      share: { rows, warnings: parseShareWarnings(out.data, out.agent), reply: out.reply },
      tax: null,
    });
  }

  async function previewTax() {
    setBusy("tax");
    setError(null);
    const spouseShare = s.family.spouse ? percentsToAmounts(s.percents, estate)["배우자"] ?? 0 : 0;
    const { response, error: err } = await askAgent(s.sessionId, "상속세 계산해줘", {
      axis: "pre_need",
      family: s.family,
      context: {
        tax_input: {
          decedent_is_resident: true,
          spouse_exists: s.family.spouse,
          children_count: s.family.children,
          original_inherited_property: estate,
          financial_assets: s.financial,
          financial_debts: 0,
          debts: s.debts,
          deemed_inherited_property: 0,
          prior_gifts_to_heirs: 0,
          prior_gifts_to_non_heirs: 0,
          ...(s.family.spouse ? { spouse_actual_inheritance: spouseShare } : {}),
          filing_within_deadline: true,
        },
      },
    });
    setBusy(null);
    if (err || !response) return setError(err);
    const out = contributionOf(response, "tax_calculator");
    const result = out ? parseTaxResult(out.data, out.agent) : null;
    if (!out || !result) {
      setError("상속세 계산 에이전트가 추가 확인이 필요하다고 했어요. 아래 설명을 확인해주세요.");
      update({ tax: null });
      return;
    }
    update({ tax: { result, reply: out.reply } });
  }

  function setPercent(name: string, value: number) {
    update({
      percents: { ...s.percents, [name]: Math.max(0, Math.min(100, Math.round(value))) },
      share: null,
      tax: null,
    });
  }

  function initPercents(family: Family) {
    update({ family, percents: statutoryPercents(family), share: null, tax: null });
  }

  // ---------------------------------------------------------------- 1. 자산

  if (step === "assets") {
    return (
      <MobileShell
        title="상속설계"
        onBack={() => navigate("/m")}
        step={1}
        total={TOTAL_STEPS}
        cta={
          <Cta onClick={() => go("family")} disabled={estate <= 0}>
            다음
          </Cta>
        }
      >
        <Heading eyebrow="상속설계를 도와드릴게요" title="상속할 자산을 알려주세요" />
        <section className="m-sunken">
          <AmountField
            label="예금·주식 등 금융자산"
            value={s.financial}
            onChange={(v) => update({ financial: v, share: null, tax: null })}
          />
        </section>
        <AmountField
          label="부동산 등 기타 자산"
          help="시세를 모르면 공시가격이나 대략적인 금액도 괜찮아요."
          value={s.other}
          onChange={(v) => update({ other: v, share: null, tax: null })}
        />
        <AmountField
          label="대출 등 갚아야 할 빚"
          value={s.debts}
          onChange={(v) => update({ debts: v, share: null, tax: null })}
        />

        <section className="m-card m-card-agent">
          <h3 className="m-card-title">금액 정리가 어렵다면, 말로 알려주세요</h3>
          <p className="m-help">자산정리 에이전트가 항목을 나눠 위 칸을 채워드려요.</p>
          <textarea
            className="m-textarea"
            rows={2}
            value={assetText}
            placeholder="예: 아파트 5억, 예금 3천만, 주담대 1억"
            onChange={(e) => setAssetText(e.target.value)}
          />
          {busy === "asset" ? (
            <Thinking agent="asset_organizer" text="자산을 정리하고 있어요…" />
          ) : (
            <button
              type="button"
              className="m-chip m-chip-strong"
              disabled={!assetText.trim()}
              onClick={() => void organizeAssets()}
            >
              에이전트에게 정리 맡기기
            </button>
          )}
          {assetNote && <p className="m-note">{assetNote}</p>}
          {error && <ErrorBox message={error} onRetry={() => void organizeAssets()} />}
        </section>
      </MobileShell>
    );
  }

  // ---------------------------------------------------------------- 2. 가족

  if (step === "family") {
    return (
      <MobileShell
        title="상속설계"
        onBack={() => go("assets")}
        step={2}
        total={TOTAL_STEPS}
        cta={
          <Cta
            disabled={names.length === 0}
            onClick={() => {
              if (!Object.keys(s.percents).length) initPercents(s.family);
              go("shares");
            }}
          >
            다음
          </Cta>
        }
      >
        <Heading eyebrow="누구에게 남기실 건가요?" title="가족 구성을 알려주세요" />
        <section className="m-card">
          <h3 className="m-card-title">배우자가 있으신가요?</h3>
          <ChoiceButtons
            columns={2}
            value={s.family.spouse}
            options={[
              { label: "있어요", value: true },
              { label: "없어요", value: false },
            ]}
            onSelect={(v) => initPercents({ ...s.family, spouse: v })}
          />
        </section>
        <section className="m-card">
          <h3 className="m-card-title">자녀는 몇 명인가요?</h3>
          <Counter
            value={s.family.children}
            onChange={(v) => initPercents({ ...s.family, children: v })}
          />
        </section>
        <p className="m-help">
          부모님·형제자매만 있는 경우 등은 PC 상담에서 더 자세히 볼 수 있어요.
        </p>
      </MobileShell>
    );
  }

  // ---------------------------------------------------------------- 3. 비율

  if (step === "shares") {
    const remain = 100 - percentTotal;
    return (
      <MobileShell
        title="상속설계"
        onBack={() => go("family")}
        step={3}
        total={TOTAL_STEPS}
        cta={
          <Cta
            disabled={remain !== 0}
            onClick={() => {
              go("check");
              void checkShares();
            }}
          >
            {remain === 0 ? "유류분 확인하기" : remain > 0 ? `남은 ${remain}%를 나눠주세요` : `${-remain}% 초과했어요`}
          </Cta>
        }
      >
        <Heading eyebrow="얼마씩 나눌까요?" title="나눌 비율을 정해주세요" />
        <div className="m-stat-row">
          <div>
            <small>상속자산</small>
            <b>{won(estate)}</b>
          </div>
          <div>
            <small>설정된 비율</small>
            <b className={remain === 0 ? "is-ok" : "is-warn"}>
              {percentTotal}% <small>/ 100%</small>
            </b>
          </div>
        </div>
        {names.map((name, i) => (
          <section key={name} className="m-card m-share-card">
            <div className="m-share-top">
              <div className="m-share-who">
                <Avatar name={name} index={i} />
                <b>{name}</b>
              </div>
              <div className="m-share-input">
                <label>
                  <input
                    inputMode="numeric"
                    aria-label={`${name} 비율 직접 입력`}
                    value={s.percents[name] ?? 0}
                    onChange={(e) => setPercent(name, Number(e.target.value.replace(/[^\d]/g, "")) || 0)}
                  />
                  <span>%</span>
                </label>
                <small>{won(amounts[name])}</small>
              </div>
            </div>
            <input
              type="range"
              className="m-range"
              min={0}
              max={100}
              step={1}
              aria-label={`${name} 비율`}
              aria-valuetext={`${s.percents[name] ?? 0}%`}
              value={s.percents[name] ?? 0}
              style={{ "--fill": `${s.percents[name] ?? 0}%`, "--thumb": HEIR_COLORS[i % HEIR_COLORS.length] } as CSSProperties}
              onChange={(e) =>
                update({
                  percents: rebalancePercents(
                    Object.fromEntries(names.map((n) => [n, s.percents[n] ?? 0])),
                    name,
                    Number(e.target.value),
                  ),
                  share: null,
                  tax: null,
                })
              }
            />
            <div className="m-range-scale" aria-hidden="true">
              <span>0%</span>
              <span>50%</span>
              <span>100%</span>
            </div>
          </section>
        ))}
        <div className="m-row m-row-2">
          <button type="button" className="m-outline-btn" onClick={() => initPercents(s.family)}>
            ↺ 법정비율로
          </button>
          <button
            type="button"
            className="m-outline-btn"
            onClick={() => {
              const first = names[0];
              if (first && remain > 0) {
                update({
                  percents: { ...s.percents, [first]: (s.percents[first] ?? 0) + remain },
                  share: null,
                });
              }
            }}
            disabled={remain <= 0}
          >
            남은 비율 {names[0] ?? ""}에게
          </button>
        </div>
        <p className="m-help">
          막대를 밀면 나머지 가족 비율이 자동으로 맞춰져 합계가 100%로 유지돼요. 숫자를 눌러 한 사람만 직접 고칠 수도 있어요. 처음 값은 민법의 법정상속분(배우자 1.5 : 자녀 1)이에요. 유언이나 신탁으로 원하는
          비율을 정할 수 있어요.
        </p>
      </MobileShell>
    );
  }

  // ---------------------------------------------------------------- 4. 유류분 신호등

  if (step === "check") {
    const rows = s.share?.rows ?? [];
    const short = rows.filter((r) => (r.simple_gap ?? 0) > 0);
    return (
      <MobileShell
        title="상속설계"
        onBack={() => go("shares")}
        step={4}
        total={TOTAL_STEPS}
        secondary={
          short.length > 0 ? (
            <Cta variant="ghost" onClick={() => go("result")}>
              그대로 결과 보기
            </Cta>
          ) : undefined
        }
        cta={
          !s.share ? (
            <Cta onClick={() => void checkShares()} disabled={busy === "share"}>
              {busy === "share" ? "확인하는 중…" : "유류분 확인하기"}
            </Cta>
          ) : short.length > 0 ? (
            <Cta onClick={() => go("shares")}>비율 다시 조정하기</Cta>
          ) : (
            <Cta onClick={() => go("result")}>결과 보기</Cta>
          )
        }
      >
        <Heading eyebrow="가족 모두 최소한의 몫을 받나요?" title="유류분 신호등" />
        {busy === "share" && <Thinking agent="heir_share_analyzer" text="유류분을 계산하고 있어요…" />}
        {error && <ErrorBox message={error} onRetry={() => void checkShares()} onLater={() => navigate("/m")} />}
        {s.share && (
          <>
            <div className="m-filter" role="list">
              <span className="m-pill is-on">전체 {rows.length}</span>
              <span className="m-pill m-pill-ok">● 충족 {rows.length - short.length}</span>
              <span className="m-pill m-pill-bad">● 미달 {short.length}</span>
            </div>
            {rows.map((r, i) => {
              const gap = r.simple_gap ?? 0;
              const planned = r.planned_acquisition ?? 0;
              const forced = r.basic_forced_share_estimate ?? 0;
              return (
                <section key={r.heir} className="m-card">
                  <div className="m-share-who m-share-who-row">
                    <Avatar name={r.heir} index={i} />
                    <div>
                      <b>{r.heir}</b>
                      <p className={gap > 0 ? "m-sig m-sig-bad" : "m-sig m-sig-ok"}>
                        <span aria-hidden="true">{gap > 0 ? "▲" : "●"}</span>{" "}
                        {gap > 0
                          ? `유류분보다 약 ${wonShort(gap)} 부족`
                          : `유류분보다 약 ${wonShort(planned - forced)} 많아요`}
                      </p>
                    </div>
                  </div>
                  <dl className="m-dl">
                    <div className="m-dl-strong">
                      <dt>내가 정한 금액</dt>
                      <dd>{won(planned)}</dd>
                    </div>
                    <div>
                      <dt>법정상속분 ({r.statutory_share_fraction})</dt>
                      <dd>{won(r.statutory_share_amount)}</dd>
                    </div>
                    <div>
                      <dt>유류분 ({r.forced_share_rate_fraction})</dt>
                      <dd>{won(forced)}</dd>
                    </div>
                  </dl>
                </section>
              );
            })}
            <AgentNote
              agent="heir_share_analyzer"
              summary={
                short.length
                  ? `${short.map((r) => r.heir).join(", ")}님 몫이 유류분보다 적어요. 나중에 다툼이 생길 수 있어요.`
                  : "모든 분이 유류분 이상을 받아요. 다툼 가능성이 낮은 설계예요."
              }
              reply={s.share.reply}
            />
            <AskChips
              sessionId={s.sessionId}
              axis="pre_need"
              family={s.family}
              questions={
                short.length
                  ? ["유류분이 뭐예요?", "부족한 몫을 채우려면 어떻게 해요?"]
                  : ["유류분이 뭐예요?", "생전에 증여하면 달라져요?"]
              }
            />
          </>
        )}
      </MobileShell>
    );
  }

  // ---------------------------------------------------------------- 5. 결과

  if (step === "result") {
    const parts = names.map((n, i) => ({
      name: n,
      value: s.percents[n] ?? 0,
      color: HEIR_COLORS[i % HEIR_COLORS.length],
    }));
    return (
      <MobileShell
        title="나의 상속노트"
        tone="warm"
        onBack={() => go("check")}
        cta={
          <Cta onClick={() => (s.tax ? go("tax") : (go("tax"), void previewTax()))}>
            {s.tax ? "상속세 결과 보기" : "상속세 미리보기"}
          </Cta>
        }
      >
        <section className="m-card">
          <h2 className="m-card-h">상속 설계 결과</h2>
          <p className="m-help">
            유언대용신탁이나 유언을 활용하면 법정상속분과 다르게, 내가 설계한 대로 나눠줄 수
            있어요.
          </p>
          <Donut parts={parts} label="상속비율" />
          <dl className="m-dl m-sunken">
            <div className="m-dl-strong">
              <dt>상속할 자산</dt>
              <dd>{won(estate)}</dd>
            </div>
            <div>
              <dt>금융자산</dt>
              <dd>{won(s.financial)}</dd>
            </div>
            <div>
              <dt>부동산 등 기타</dt>
              <dd>{won(s.other)}</dd>
            </div>
            {s.debts > 0 && (
              <div>
                <dt>빚</dt>
                <dd>−{won(s.debts)}</dd>
              </div>
            )}
          </dl>
        </section>

        <section className="m-card">
          <h2 className="m-card-h">상속 설계 상세</h2>
          {names.map((n, i) => (
            <div key={n} className="m-detail-row" style={{ borderColor: HEIR_COLORS[i % HEIR_COLORS.length] }}>
              <b>{n}</b>
              <span>
                {won(percentsToAmounts(s.percents, estate)[n])} <small>({s.percents[n] ?? 0}%)</small>
              </span>
            </div>
          ))}
          {s.share &&
            (s.share.rows.some((r) => (r.simple_gap ?? 0) > 0) ? (
              <p className="m-sig m-sig-bad">▲ 유류분 미달인 분이 있어요</p>
            ) : (
              <p className="m-sig m-sig-ok">● 모든 분이 유류분을 충족해요</p>
            ))}
        </section>

        <h3 className="m-section-label">다음으로 해볼 일</h3>
        <NextCard eyebrow="세금은 얼마나?" title="이 설계대로 상속세 미리보기" tone="gold" onClick={() => (s.tax ? go("tax") : (go("tax"), void previewTax()))} />
        <NextCard eyebrow="설계대로 나누려면" title="유언대용신탁 알아보기" onClick={() => navigate("/m/tips/trust")} />
        <NextCard eyebrow="비율을 바꿔보고 싶다면" title="나눌 비율 다시 정하기" onClick={() => go("shares")} />
      </MobileShell>
    );
  }

  // ---------------------------------------------------------------- 6. 상속세

  const tax = s.tax?.result;
  return (
    <MobileShell
      title="상속세 미리보기"
      onBack={() => go("result")}
      cta={
        tax ? (
          <Cta onClick={() => void share()}>이 설계 저장·가족에게 공유</Cta>
        ) : (
          <Cta onClick={() => void previewTax()} disabled={busy === "tax"}>
            {busy === "tax" ? "계산하는 중…" : "상속세 계산하기"}
          </Cta>
        )
      }
    >
      <Heading eyebrow="지금 설계대로라면" title="예상 상속세" />
      {busy === "tax" && <Thinking agent="tax_calculator" text="공제와 세율을 적용하고 있어요…" />}
      {error && <ErrorBox message={error} onRetry={() => void previewTax()} onLater={() => navigate("/m")} />}
      {tax && (
        <>
          <section className="m-card m-hero-amount">
            <small>최종 예상 상속세</small>
            <b>{won(tax.final_amount)}</b>
            <p className="m-help">상속재산 {wonShort(estate)} 기준 · 기한 내 신고 가정</p>
          </section>
          <section className="m-card">
            <h3 className="m-card-title">계산 내역</h3>
            <dl className="m-dl">
              {tax.rows.map((r) => (
                <div key={r.label} className={r.label.includes("최종") ? "m-dl-strong" : ""}>
                  <dt>{r.label}</dt>
                  <dd>{won(r.amount)}</dd>
                </div>
              ))}
            </dl>
          </section>
          <AgentNote
            agent="tax_calculator"
            summary={
              (tax.final_amount ?? 0) === 0
                ? "공제 범위 안이라 상속세가 없을 것으로 보여요."
                : "배우자·일괄·금융재산 공제를 반영했어요. 참고용 시뮬레이션이에요."
            }
            reply={s.tax?.reply}
          />
          <AskChips
            sessionId={s.sessionId}
            axis="pre_need"
            family={s.family}
            questions={["세금을 줄이는 방법이 있나요?", "배우자 공제는 어떻게 계산돼요?", "미리 증여하면 달라져요?"]}
          />
          <h3 className="m-section-label">다음으로 해볼 일</h3>
          <NextCard eyebrow="비율을 바꾸면 세금도 달라져요" title="나눌 비율 다시 정하기" onClick={() => go("shares")} />
          <NextCard eyebrow="자세한 상담을 원하면" title="PC 상담에서 이어하기" onClick={() => navigate("/chat")} />
          <NextCard
            eyebrow="가족이 이미 떠나셨다면"
            title="사망 후 절차 안내 받기"
            tone="navy"
            onClick={() => navigate("/m/after")}
          />
          <button type="button" className="m-link-btn m-center" onClick={() => { reset(); navigate("/m/prepare/assets"); }}>
            처음부터 새로 설계하기
          </button>
        </>
      )}
    </MobileShell>
  );

  async function share() {
    const lines = [
      "[EZNEXT 나의 상속노트]",
      `상속할 자산: ${won(estate)}`,
      ...names.map((n) => `- ${n}: ${s.percents[n] ?? 0}% (${won(percentsToAmounts(s.percents, estate)[n])})`),
      tax ? `예상 상속세: ${won(tax.final_amount)}` : "",
      `${window.location.origin}/m/prepare`,
    ].filter(Boolean);
    const text = lines.join("\n");
    try {
      if (navigator.share) await navigator.share({ title: "나의 상속노트", text });
      else {
        await navigator.clipboard.writeText(text);
        alert("설계 내용을 복사했어요. 가족에게 붙여넣어 보내주세요.");
      }
    } catch {
      /* 사용자가 공유를 취소 */
    }
  }
}
