import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../lib/appState";
import type { ConsultAxis } from "../types";
import { Button, Eyebrow, GoldRule } from "../components/ui";

/**
 * 상담 구분 — 생전 준비(pre_need) / 사후 절차(post_death).
 * 선택 = 오케스트레이터 classify 힌트 + 이후 화면 구성 결정.
 */
export function RoleScreen() {
  const navigate = useNavigate();
  const { setAxis, axis } = useApp();
  const [selected, setSelected] = useState<ConsultAxis | null>(axis);

  const proceed = () => {
    if (!selected) return;
    setAxis(selected);
    navigate("/onboarding/family");
  };

  return (
    <div className="onboarding-screen">
      <div className="onboarding-inner">
        <Eyebrow>상담 구분</Eyebrow>
        <GoldRule />
        <h1>지금 어떤 상황이신가요?</h1>
        <p className="onboarding-lede">
          입장에 따라 준비할 항목과 안내 순서가 달라집니다. 나중에 바꿀 수 있어요.
        </p>

        <div className="role-grid">
          <RoleCard
            eyebrow="생전 준비"
            title="지금 준비 중이에요"
            body="가진 자산을 정리하고, 유언의 형식을 갖추고, 가족에게 남길 준비를 미리 하려고 합니다."
            selected={selected === "pre_need"}
            onSelect={() => setSelected("pre_need")}
          />
          <RoleCard
            eyebrow="사후 절차"
            title="가족을 떠나보낸 뒤예요"
            body="사망신고와 안심상속 원스톱, 한정승인·신고 기한, 협의와 상속세를 순서대로 챙기려고 합니다."
            selected={selected === "post_death"}
            onSelect={() => setSelected("post_death")}
          />
        </div>

        <Button block disabled={!selected} onClick={proceed}>
          다음
        </Button>
      </div>
    </div>
  );
}

function RoleCard({
  eyebrow,
  title,
  body,
  selected,
  onSelect,
}: {
  eyebrow: string;
  title: string;
  body: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`role-card${selected ? " role-card-on" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="role-card-eyebrow">{eyebrow}</span>
      <span className="role-card-title">{title}</span>
      <span className="role-card-body">{body}</span>
    </button>
  );
}
