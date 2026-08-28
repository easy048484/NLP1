import { useState } from "react";
import { Topbar } from "./Topbar";

const STEPS = ["거주자", "재산", "채무", "금융", "신고", "시산"];

export function TaxWizardScreen() {
  const [step, setStep] = useState(0);
  const [resident, setResident] = useState<"yes" | "no" | null>("yes");

  return (
    <div className="screen">
      <Topbar title="상속세 시산" subtitle="재산가액을 단계적으로 입력합니다." />
      <div className="screen-scroll">
        <div className="stepper">
          {STEPS.map((_, i) => (
            <i key={STEPS[i]} className={i <= step ? "on" : ""} />
          ))}
        </div>
        <p className="muted" style={{ marginTop: 0 }}>
          {step + 1} / {STEPS.length} · {STEPS[step]} · 가족관계는 반영됨
        </p>

        {step === 0 && (
          <>
            <div className="bubble bubble-assistant">
              피상속인께서 사망 당시 국내 거주자이셨습니까?
            </div>
            <div className="choice-row">
              <button
                type="button"
                className={`choice-btn${resident === "yes" ? " choice-on" : ""}`}
                onClick={() => setResident("yes")}
              >
                예
              </button>
              <button
                type="button"
                className={`choice-btn${resident === "no" ? " choice-on" : ""}`}
                onClick={() => setResident("no")}
              >
                아니오
              </button>
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <div className="bubble bubble-assistant">본래의 상속재산 가액은 얼마입니까?</div>
            <div className="amount-grid">
              {["3억 원", "5억 원", "10억 원", "직접 입력"].map((label) => (
                <button key={label} type="button" className="amount-chip">
                  {label}
                </button>
              ))}
            </div>
          </>
        )}

        {step >= 2 && (
          <div className="tax-result">
            <div className="label">예상 산출세액</div>
            <div className="won">1,240만 원</div>
            <p className="muted" style={{ color: "#cbbfaa" }}>
              배우자 공제·금융재산 공제를 반영한 시산입니다. 실제 신고세액이 아닙니다.
            </p>
          </div>
        )}

        <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
          <button
            type="button"
            className="choice-btn"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
          >
            이전
          </button>
          <button
            type="button"
            className="cta"
            style={{ marginTop: 0 }}
            onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
          >
            {step >= STEPS.length - 1 ? "현황에 반영" : "다음"}
          </button>
        </div>
      </div>
    </div>
  );
}

const REQS: { title: string; grade: "green" | "yellow" | "red"; label: string; body: string }[] =
  [
    {
      title: "유언자 성명",
      grade: "green",
      label: "충족",
      body: "본문에서 유언자 본인 성명이 확인됩니다.",
    },
    {
      title: "작성 연월일",
      grade: "green",
      label: "충족",
      body: "2026년 5월 3일로 특정할 수 있습니다.",
    },
    {
      title: "주소",
      grade: "yellow",
      label: "보완",
      body: "시·구 기재까지 확인됩니다. 번지 보완을 권합니다.",
    },
    {
      title: "자필",
      grade: "green",
      label: "충족",
      body: "자필 작성으로 안내된 초안입니다. 원본 확인이 필요합니다.",
    },
    {
      title: "날인",
      grade: "red",
      label: "미비",
      body: "날인 흔적이 확인되지 않았습니다.",
    },
  ];

export function WillCheckScreen() {
  return (
    <div className="screen">
      <Topbar title="유언 요건 점검" subtitle="자필증서 · 형식 확인" />
      <div className="screen-scroll">
        <p className="muted" style={{ marginTop: 0 }}>
          유효·무효를 단정하지 않습니다. 요건별로 판례·조문에 비춘 점검 결과만 보여 드립니다.
        </p>
        <div className="req-list">
          {REQS.map((req) => (
            <div key={req.title} className="req">
              <div className="req-head">
                <h3>{req.title}</h3>
                <span className={`light light-${req.grade}`}>{req.label}</span>
              </div>
              <p>{req.body}</p>
            </div>
          ))}
        </div>
        <div className="precedent">
          주소가 동만 기재된 사안에서 무효로 판단한 판례가 있습니다. (2012다71688)
        </div>
        <p className="disclaimer">
          이 결과는 법률 자문이 아니며, 유언장 원문은 저장하지 않습니다.
        </p>
      </div>
    </div>
  );
}
