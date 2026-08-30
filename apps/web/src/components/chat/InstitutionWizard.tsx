import { useState } from "react";
import { useApp } from "../../lib/appState";
import { Button, Card, ChoiceGroup } from "../ui";

/**
 * 조회결과 해석 위저드 (시나리오 A 핵심).
 * 안심상속 원스톱 등에서 받은 조회결과를 "말로 설명"하는 부담을 낮춘다.
 * 시니어 UX(토스 리서치): 라벨은 의문형이 아니라 상태 그 자체. 예시 문장 병기.
 */
type Status = "balance" | "account_only" | "none";

interface Institution {
  key: string;
  label: string;
  example: string;
}

const INSTITUTIONS: Institution[] = [
  { key: "bank", label: "은행", example: "예: 국민은행은 잔액까지, 신한은행은 계좌만 나왔어요" },
  { key: "insurance", label: "보험", example: "예: 삼성생명에 보험계약이 있다고 나왔어요" },
  { key: "securities", label: "증권 · 투자", example: "예: 미래에셋 계좌가 있다고만 나왔어요" },
  { key: "realty", label: "부동산 · 자동차", example: "예: 아파트 1건, 자동차 1대가 확인됐어요" },
  { key: "pension", label: "연금", example: "예: 국민연금 유족연금 대상이라고 나왔어요" },
];

const STATUS_OPTIONS: { label: string; value: Status }[] = [
  { label: "잔액까지 나왔어요", value: "balance" },
  { label: "계좌만 확인됐어요", value: "account_only" },
  { label: "안 나왔어요", value: "none" },
];

const STATUS_TEXT: Record<Status, string> = {
  balance: "잔액까지 확인",
  account_only: "계좌만 확인",
  none: "확인 안 됨",
};

export function InstitutionWizard({ onClose }: { onClose: () => void }) {
  const { send } = useApp();
  const [answers, setAnswers] = useState<Record<string, { status: Status; note: string }>>({});

  const setStatus = (key: string, status: Status) =>
    setAnswers((prev) => ({ ...prev, [key]: { status, note: prev[key]?.note ?? "" } }));
  const setNote = (key: string, note: string) =>
    setAnswers((prev) => ({
      ...prev,
      [key]: { status: prev[key]?.status ?? "none", note },
    }));

  const answered = Object.keys(answers).length;

  const finish = () => {
    const lines = INSTITUTIONS.filter((i) => answers[i.key]).map((i) => {
      const a = answers[i.key];
      return `- ${i.label}: ${STATUS_TEXT[a.status]}${a.note ? ` (${a.note})` : ""}`;
    });
    void send(`조회결과를 정리했어요.\n${lines.join("\n")}`);
    onClose();
  };

  return (
    <div className="inst-wizard">
      <div className="inst-wizard-head">
        <h3>조회결과 정리</h3>
        <p>기관별로 지금 상태를 골라 주세요. 어려우면 예시 문장을 참고하시면 됩니다.</p>
      </div>

      {INSTITUTIONS.map((inst) => (
        <Card key={inst.key} className="inst-card">
          <div className="inst-card-label">{inst.label}</div>
          <ChoiceGroup<Status>
            ariaLabel={`${inst.label} 상태`}
            options={STATUS_OPTIONS}
            value={answers[inst.key]?.status}
            onSelect={(v) => setStatus(inst.key, v)}
          />
          <input
            className="inst-note"
            type="text"
            placeholder="어느 곳인지 적어 주세요 (생략 가능)"
            aria-label={`${inst.label} 메모`}
            value={answers[inst.key]?.note ?? ""}
            onChange={(e) => setNote(inst.key, e.target.value)}
          />
          <p className="inst-example">{inst.example}</p>
        </Card>
      ))}

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
