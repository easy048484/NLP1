import { useNavigate } from "react-router-dom";
import { useApp } from "../lib/appState";
import { buildPrep, prepPercent } from "../lib/prep";
import { AXIS_LABEL } from "../lib/consult";
import { Button, Eyebrow, Gauge, StatusPill } from "../components/ui";

/**
 * 준비 현황 홈 (통장형 준비도). 생전 축의 기본 착지 화면.
 */
export function HomeScreen() {
  const navigate = useNavigate();
  const { auth, axis, familyGraph, plan, planChecks, estate, willStatus } = useApp();

  const prep = buildPrep({ axis, familyGraph, plan, planChecks, estate, willStatus });
  const percent = prepPercent(prep);
  const nextItem = prep.find((p) => p.status !== "done");

  return (
    <div className="home-screen">
      <section className="ledger-card">
        <div className="ledger-hello">
          {auth ? `${auth.user.name} 님의 준비 현황` : "나의 준비 현황"}
          {axis && <span className="ledger-axis">{AXIS_LABEL[axis]}</span>}
        </div>
        <h1 className="ledger-title">
          {axis === "pre_need"
            ? "남길 준비를 차근차근"
            : axis === "post_death"
              ? "남겨진 일을 빠짐없이"
              : "가족의 다음을 순서대로"}
        </h1>
        <Gauge tone="inverse" label="준비도" valueText={`${percent}%`} percent={percent} />
      </section>

      {nextItem && (
        <section className="home-next">
          <Eyebrow>이어서 하기</Eyebrow>
          <p className="home-next-title">{nextItem.title}</p>
          <p className="home-next-desc">{nextItem.desc}</p>
          <Button onClick={() => navigate(nextItem.route)}>이어서 하기</Button>
        </section>
      )}

      <section className="home-prep">
        <h2>준비 항목</h2>
        <ul className="home-prep-list">
          {prep.map((item) => (
            <li key={item.key}>
              <button
                type="button"
                className="home-prep-item"
                onClick={() => navigate(item.route)}
              >
                <span className="home-prep-title">{item.title}</span>
                <StatusPill kind={item.status} label={item.statusLabel} />
                <span className="home-prep-desc">{item.desc}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <Button variant="outline" block onClick={() => navigate("/chat")}>
        상담 시작하기
      </Button>
    </div>
  );
}
