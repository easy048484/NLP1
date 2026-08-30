import { useMemo, useState } from "react";
import { useApp } from "../../lib/appState";
import { Button, Card, ChoiceGroup } from "../ui";
import { parseKrw } from "../../lib/format";

/**
 * 조회결과 해석 위저드 (시나리오 A 핵심).
 * 안심상속 원스톱 등에서 받은 조회결과를 "말로 설명"하는 부담을 낮춘다.
 * "잔액까지 나왔어요"를 고르면 금액칸이 열리고, 정리 결과를 asset_organizer 가
 * 바로 읽을 수 있는 구조화 답변(context.asset_organizer)으로 보낸다.
 */
type Status = "balance" | "account_only" | "none";

interface Institution {
  key: string;
  label: string;
  example: string;
  /** asset_organizer 카테고리 (자산). */
  assetTypes?: string[];
  /** 부채/보험이면 별도 처리. */
  kind?: "liability" | "insurance";
}

const INSTITUTIONS: Institution[] = [
  { key: "bank", label: "은행 예금", example: "예: 국민은행 잔액 3,200만원", assetTypes: ["예금"] },
  { key: "securities", label: "증권 · 펀드", example: "예: 미래에셋 계좌 1,500만원", assetTypes: ["주식", "펀드"] },
  { key: "realty", label: "부동산", example: "예: 공시가격 3억 5천만원", assetTypes: ["부동산"] },
  { key: "car", label: "자동차", example: "예: 시세 800만원", assetTypes: ["자동차"] },
  { key: "pension", label: "퇴직연금", example: "예: 적립금 4,000만원", assetTypes: ["퇴직연금"] },
  { key: "insurance", label: "보험", example: "예: 삼성생명 종신보험 가입", kind: "insurance" },
  { key: "loan", label: "대출 · 채무", example: "예: 주택담보대출 잔액 1억 2천만원", kind: "liability" },
];

const STATUS_OPTIONS: { label: string; value: Status }[] = [
  { label: "잔액까지 나왔어요", value: "balance" },
  { label: "계좌만 확인됐어요", value: "account_only" },
  { label: "없어요 / 안 나왔어요", value: "none" },
];

const CATEGORY_ORDER = [
  "예금",
  "주식",
  "펀드",
  "부동산",
  "자동차",
  "퇴직연금",
  "부채",
  "보험",
];

type Answer = { status: Status; amount: string };

export function InstitutionWizard({ onClose }: { onClose: () => void }) {
  const { send } = useApp();
  const [answers, setAnswers] = useState<Record<string, Answer>>({});

  const setStatus = (key: string, status: Status) =>
    setAnswers((prev) => ({ ...prev, [key]: { status, amount: prev[key]?.amount ?? "" } }));
  const setAmount = (key: string, amount: string) =>
    setAnswers((prev) => ({
      ...prev,
      [key]: { status: prev[key]?.status ?? "none", amount },
    }));

  const answered = Object.keys(answers).length;

  const summary = useMemo(() => {
    const assets: { type: string; value: number; liquid: null; return_rate: null }[] = [];
    const liabilities: {
      type: string;
      remaining_balance: number;
      monthly_payment: null;
      end_age: null;
      note: null;
    }[] = [];
    const insurance: { type: string; value: number; note: string }[] = [];
    const needsLookup: string[] = [];
    const lines: string[] = [];

    for (const inst of INSTITUTIONS) {
      const a = answers[inst.key];
      if (!a) continue;
      const amount = a.status === "balance" ? parseKrw(a.amount) : null;

      // ⚠️ 메시지 텍스트에는 금액을 넣지 않는다 — asset_organizer 가 이 턴을
      //    후속질문 답변으로 오인해 텍스트에서 숫자를 긁어가는 걸 막는다.
      //    실제 금액은 아래 context.asset_organizer 로만 전달한다.
      if (a.status === "balance" && amount != null && amount > 0) {
        if (inst.kind === "liability") {
          liabilities.push({
            type: "대출",
            remaining_balance: amount,
            monthly_payment: null,
            end_age: null,
            note: null,
          });
          lines.push(`- ${inst.label}: 잔액 확인됨`);
        } else if (inst.kind === "insurance") {
          insurance.push({ type: "보험", value: amount, note: "안심상속 조회로 확인" });
          lines.push(`- ${inst.label}: 확인됨`);
        } else {
          // 금액은 첫 유형에만 싣는다 (증권·펀드처럼 한 칸에 묶인 경우).
          (inst.assetTypes ?? []).forEach((t, idx) => {
            assets.push({
              type: t,
              value: idx === 0 ? amount : 0,
              liquid: null,
              return_rate: null,
            });
          });
          lines.push(`- ${inst.label}: 잔액 확인됨`);
        }
      } else if (a.status === "account_only") {
        needsLookup.push(inst.label);
        lines.push(`- ${inst.label}: 계좌만 확인 (금액 미상)`);
      } else if (a.status === "none") {
        if (inst.kind === "insurance") insurance.push({ type: "보험", value: 0, note: "없음" });
        lines.push(`- ${inst.label}: 없음`);
      }
    }

    return { assets, liabilities, insurance, needsLookup, lines };
  }, [answers]);

  const finish = () => {
    const message = [
      "안심상속 통합조회 결과를 정리했어요.",
      ...summary.lines,
      summary.needsLookup.length
        ? `\n계좌만 확인된 곳(${summary.needsLookup.join(", ")})은 해당 기관에 개별 문의가 필요해요.`
        : "",
    ]
      .filter(Boolean)
      .join("\n");

    void send(message, {
      context: {
        asset_organizer: {
          assets: summary.assets,
          liabilities: summary.liabilities,
          insurance: summary.insurance,
          checked_categories: CATEGORY_ORDER,
          // 위저드가 부채·퇴직연금 후속질문 대상을 이미 정리했다고 본다.
          liability_followup_asked: true,
          pension_followup_asked: true,
          pension_followup_resolved: true,
        },
      },
    });
    onClose();
  };

  return (
    <div className="inst-wizard">
      <div className="inst-wizard-head">
        <h3>조회결과 정리</h3>
        <p>
          기관별로 지금 상태를 골라 주세요. 잔액이 나온 곳은 금액을 적으면 예상 상속세·유류분
          계산에 바로 반영됩니다.
        </p>
      </div>

      {INSTITUTIONS.map((inst) => {
        const a = answers[inst.key];
        return (
          <Card key={inst.key} className="inst-card">
            <div className="inst-card-label">{inst.label}</div>
            <ChoiceGroup<Status>
              ariaLabel={`${inst.label} 상태`}
              options={STATUS_OPTIONS}
              value={a?.status}
              onSelect={(v) => setStatus(inst.key, v)}
            />
            {a?.status === "balance" && (
              <input
                className="inst-amount"
                type="text"
                inputMode="numeric"
                placeholder="금액 (예: 3천만원 / 32000000)"
                aria-label={`${inst.label} 금액`}
                value={a.amount}
                onChange={(e) => setAmount(inst.key, e.target.value)}
              />
            )}
            <p className="inst-example">{inst.example}</p>
          </Card>
        );
      })}

      <div className="inst-wizard-actions">
        <Button variant="ghost" onClick={onClose}>
          나중에 할게요
        </Button>
        <Button onClick={finish} disabled={answered === 0}>
          이대로 정리하기
        </Button>
      </div>
    </div>
  );
}
