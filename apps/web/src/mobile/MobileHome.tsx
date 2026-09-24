/**
 * /m — 모바일 간단 버전 홈. 두 입구(부모님용·자녀용) + 이어하기 배너 + 팁.
 * /m/tips/:id — 팁 글. 글 끝은 항상 해당 흐름 시작 버튼으로 이어진다.
 */
import { useNavigate, useParams } from "react-router-dom";
import { AFTER_KEY, PREPARE_KEY, readSavedStep } from "./lib";
import { Cta, MobileShell, NextCard } from "./ui";

const PREPARE_LABEL: Record<string, string> = {
  assets: "자산 확인",
  family: "가족 구성",
  shares: "나눌 비율",
  check: "유류분 신호등",
  result: "설계 결과",
  tax: "상속세 미리보기",
};
const AFTER_LABEL: Record<string, string> = {
  check: "진행 상황 확인",
  plan: "해야 할 일",
  will: "유언장 점검",
};

interface Tip {
  id: string;
  eyebrow: string;
  title: string;
  tags: string;
  lead: string;
  sections: { h: string; body: string }[];
  flow: "prepare" | "after";
  ctaLabel: string;
}

const TIPS: Tip[] = [
  {
    id: "trust",
    eyebrow: "상속도 내가 원하는 대로",
    title: "유언대용신탁 알아보기",
    tags: "#상속 #신탁 #생전준비",
    lead: "복잡한 유언장 없이도 원하는 사람에게, 원하는 시기에 재산을 남기는 방법이에요.",
    sections: [
      {
        h: "1. 내 자산을 내 뜻대로 남기는 방법",
        body: "유언은 형식 요건이 까다로워 무효가 되는 경우가 많아요. 유언대용신탁은 금융회사와 계약으로 '내가 떠난 뒤 누구에게 얼마를' 정해두는 방식이라 분쟁 소지를 줄일 수 있어요.",
      },
      {
        h: "2. 이렇게 활용해요",
        body: "배우자에게 먼저 생활비로 나눠 지급하고, 배우자가 떠난 뒤 자녀에게 넘기는 식으로 순서를 설계할 수 있어요. 미성년·장애 자녀를 위한 분할 지급도 가능해요.",
      },
      {
        h: "3. 유언대용신탁 vs 유언장",
        body: "둘 다 유류분(가족의 최소 몫) 문제는 남아요. 설계 전에 가족별 유류분을 먼저 확인해 두면 나중에 다툼을 줄일 수 있어요.",
      },
    ],
    flow: "prepare",
    ctaLabel: "내 상속설계에서 유류분 확인하기",
  },
  {
    id: "forced-share",
    eyebrow: "가족의 최소한의 몫",
    title: "유류분, 이것만 알면 돼요",
    tags: "#유류분 #법정상속분",
    lead: "유언으로도 빼앗을 수 없는 가족의 최소 몫이 유류분이에요.",
    sections: [
      { h: "누가 받을 수 있나요?", body: "배우자와 자녀는 법정상속분의 1/2, 부모는 1/3이에요. 형제자매는 2024년 헌법재판소 결정 이후 유류분이 없어요." },
      { h: "부족하면 어떻게 되나요?", body: "상속이 시작된 뒤 부족한 가족이 청구할 수 있어요. 미리 비율을 조정해 두면 다툼을 막을 수 있어요." },
    ],
    flow: "prepare",
    ctaLabel: "우리 가족 유류분 신호등 보기",
  },
  {
    id: "deadline",
    eyebrow: "놓치면 되돌리기 어려워요",
    title: "상속, 3개월 안에 꼭 정할 것",
    tags: "#사망후절차 #상속포기 #한정승인",
    lead: "빚까지 물려받을지 정하는 기한은 '상속을 안 날'부터 3개월이에요.",
    sections: [
      { h: "사망신고 (1개월)", body: "주민센터에서 신고하면서 안심상속 원스톱 서비스로 재산·빚을 한 번에 조회 신청하세요." },
      { h: "상속포기·한정승인 (3개월)", body: "빚이 더 많거나 모르겠다면 가정법원에 한정승인을 신고해 재산 범위 안에서만 갚을 수 있어요." },
      { h: "상속세 신고 (6개월)", body: "사망일이 속한 달의 말일부터 6개월 안에 신고하면 세금 3%를 공제받아요." },
    ],
    flow: "after",
    ctaLabel: "우리 가족 기한 D-day 확인하기",
  },
];

export function MobileHome() {
  const navigate = useNavigate();
  const prepStep = readSavedStep(PREPARE_KEY);
  const afterStep = readSavedStep(AFTER_KEY);
  const resume =
    prepStep && prepStep !== "assets"
      ? { label: `상속설계 · ${PREPARE_LABEL[prepStep] ?? ""}부터`, to: `/m/prepare/${prepStep}` }
      : afterStep && afterStep !== "start"
        ? { label: `사망 후 절차 · ${AFTER_LABEL[afterStep] ?? ""}부터`, to: `/m/after/${afterStep}` }
        : null;

  return (
    <div className="m-app m-home">
      <header className="m-home-hero">
        <p className="m-home-brand">EZNEXT</p>
        <h1>
          가족의 다음을
          <br />
          <em>쉽게 설계하다</em>
        </h1>
        <p className="m-home-sub">버튼 몇 번이면 에이전트가 계산하고 안내해드려요.</p>
        {resume && (
          <button type="button" className="m-banner" onClick={() => navigate(resume.to)}>
            <span aria-hidden="true">↻</span> 이어서 {resume.label} 하실까요?
          </button>
        )}
      </header>

      <main className="m-body m-home-body">
        <section className="m-card">
          <h2 className="m-card-h">어떤 도움이 필요하세요?</h2>
          <button type="button" className="m-entry m-entry-gold" onClick={() => navigate("/m/prepare")}>
            <small>부모님·나를 위해 미리</small>
            <b>상속설계 · 상속세 미리보기</b>
            <span>누구에게 얼마를 남길지, 유류분과 세금까지 한 번에</span>
          </button>
          <button type="button" className="m-entry m-entry-navy" onClick={() => navigate("/m/after")}>
            <small>가족이 떠나셨다면</small>
            <b>사망 후 절차 · 유언장 점검</b>
            <span>오늘 할 일과 놓치면 안 되는 기한을 순서대로</span>
          </button>
        </section>

        <section className="m-card">
          <h2 className="m-card-h">알아두면 좋은 상속 팁</h2>
          {TIPS.map((t) => (
            <NextCard key={t.id} eyebrow={t.eyebrow} title={t.title} onClick={() => navigate(`/m/tips/${t.id}`)} />
          ))}
        </section>

        <section className="m-card">
          <h2 className="m-card-h">더 자세히 상담하고 싶다면</h2>
          <div className="m-row m-row-2">
            <button type="button" className="m-outline-btn" onClick={() => navigate("/chat")}>
              💬 에이전트와 대화
            </button>
            <button type="button" className="m-outline-btn" onClick={() => navigate("/")}>
              🖥 PC 버전
            </button>
          </div>
        </section>
      </main>
    </div>
  );
}

export function TipPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const tip = TIPS.find((t) => t.id === id) ?? TIPS[0];
  const others = TIPS.filter((t) => t.id !== tip.id);
  return (
    <MobileShell
      title="상속 팁"
      cta={<Cta onClick={() => navigate(`/m/${tip.flow}`)}>{tip.ctaLabel}</Cta>}
    >
      <article className="m-article">
        <p className="m-eyebrow">{tip.eyebrow}</p>
        <h2 className="m-article-title">{tip.title}</h2>
        <p className="m-tags">{tip.tags}</p>
        <p className="m-lead">{tip.lead}</p>
        <nav className="m-toc" aria-label="목차">
          {tip.sections.map((s, i) => (
            <a key={s.h} href={`#tip-${i}`}>
              {s.h}
            </a>
          ))}
        </nav>
        {tip.sections.map((s, i) => (
          <section key={s.h} id={`tip-${i}`}>
            <h3>{s.h}</h3>
            <p>{s.body}</p>
          </section>
        ))}
      </article>
      <h3 className="m-section-label">함께 보면 좋아요</h3>
      {others.map((t) => (
        <NextCard key={t.id} eyebrow={t.eyebrow} title={t.title} onClick={() => navigate(`/m/tips/${t.id}`)} />
      ))}
    </MobileShell>
  );
}
