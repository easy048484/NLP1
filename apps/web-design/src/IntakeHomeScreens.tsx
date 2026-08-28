import { useState } from "react";
import { Topbar } from "./Topbar";

export function IntakeScreen({ onNext }: { onNext: () => void }) {
  const [spouse, setSpouse] = useState<"yes" | "no" | null>("yes");
  const [children, setChildren] = useState<number | null>(null);

  return (
    <div className="screen">
      <Topbar title="가족관계 확인" subtitle="상담 전, 상속인 범위를 먼저 적어 둡니다." />
      <div className="screen-scroll">
        <p className="muted" style={{ marginTop: 0 }}>
          배우자 있음 · 이어서 자녀를 확인합니다.
        </p>
        <div className="bubble bubble-assistant">배우자가 생존해 계십니까?</div>
        <div className="choice-row">
          <button
            type="button"
            className={`choice-btn${spouse === "yes" ? " choice-on" : ""}`}
            onClick={() => setSpouse("yes")}
          >
            예
          </button>
          <button
            type="button"
            className={`choice-btn${spouse === "no" ? " choice-on" : ""}`}
            onClick={() => setSpouse("no")}
          >
            아니오
          </button>
        </div>
        {spouse === "yes" && (
          <div className="bubble bubble-user" style={{ marginBottom: 14 }}>
            예
          </div>
        )}
        <div className="bubble bubble-assistant">생존 자녀는 몇 분이십니까?</div>
        <div className="choice-row">
          {[0, 1, 2].map((n) => (
            <button
              key={n}
              type="button"
              className={`choice-btn${children === n ? " choice-on" : ""}`}
              onClick={() => setChildren(n)}
            >
              {n}명
            </button>
          ))}
          <button
            type="button"
            className={`choice-btn${children === 3 ? " choice-on" : ""}`}
            onClick={() => setChildren(3)}
          >
            3명 이상
          </button>
        </div>
        <p className="muted">
          한 번 적어 두시면, 이후 상속세·절차 상담에서 같은 질문을 반복하지 않습니다.
        </p>
        <button type="button" className="cta" onClick={onNext} disabled={children === null}>
          확인 후 저장
        </button>
      </div>
    </div>
  );
}

const PREP = [
  {
    title: "가족관계",
    desc: "배우자 김은정 · 자녀 김하준",
    status: "등록",
    kind: "done" as const,
    go: "chat" as const,
  },
  {
    title: "상속 절차",
    desc: "한정승인 기한 · 신고 일정",
    status: "진행",
    kind: "wip" as const,
    go: "chat" as const,
  },
  {
    title: "예상 상속세",
    desc: "재산가액 미입력",
    status: "대기",
    kind: "todo" as const,
    go: "tax" as const,
  },
  {
    title: "유언 요건",
    desc: "주소 기재 보완 필요",
    status: "보완",
    kind: "wip" as const,
    go: "will" as const,
  },
];

export function HomeScreen({
  onChat,
  onTax,
  onWill,
}: {
  onChat: () => void;
  onTax: () => void;
  onWill: () => void;
}) {
  return (
    <div className="screen">
      <Topbar title="준비 현황" subtitle="상속인 · 김민준" />
      <div className="screen-scroll">
        <div className="ledger">
          <div className="hello">김민준 님의 상속 준비</div>
          <h1>남겨진 일을 빠짐없이</h1>
          <div className="balance">
            <small>준비도</small>
            <strong>48%</strong>
          </div>
          <div className="bar">
            <span style={{ width: "48%" }} />
          </div>
        </div>
        <div className="prep-list">
          {PREP.map((item) => (
            <button
              key={item.title}
              type="button"
              className="prep-item"
              onClick={() => {
                if (item.go === "tax") onTax();
                else if (item.go === "will") onWill();
                else onChat();
              }}
            >
              <h3>{item.title}</h3>
              <span className={`status-pill status-${item.kind}`}>{item.status}</span>
              <p>{item.desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
