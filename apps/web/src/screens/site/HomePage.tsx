import { Link } from "react-router-dom";
import { AGENCIES, POST_DEATH_STEPS } from "../../lib/content";
import { Eyebrow } from "../../components/ui";
import { PhotoBand } from "../../components/site/Photo";
import { ParallaxImage, Reveal } from "../../components/site/Motion";

const FEATURES = [
  {
    icon: "🧭",
    title: "상속 절차 안내",
    body: "사망신고, 안심상속 원스톱, 한정승인·신고 기한을 놓치지 않도록 순서대로 안내하고 일정으로 정리합니다.",
  },
  {
    icon: "⚖️",
    title: "법정상속분 · 유류분",
    body: "등록된 가족을 기준으로 누가 얼마를 받는지, 유류분 격차는 어느 정도인지 계산해 드립니다.",
  },
  {
    icon: "📜",
    title: "유언 요건 점검",
    body: "자필증서·녹음 유언의 형식 요건을 판례에 비춰 항목별로 확인합니다. 유효·무효를 단정하지 않습니다.",
  },
  {
    icon: "🧮",
    title: "예상 상속세 시산",
    body: "재산·채무와 공제를 반영해 예상 세액을 계산합니다. 한 번 입력한 가족 정보는 다시 묻지 않습니다.",
  },
];

const STEPS = [
  { n: "01", title: "상담 구분 선택", body: "지금 준비 중인지, 가족을 떠나보낸 뒤인지 고릅니다." },
  { n: "02", title: "가족관계 등록", body: "배우자·자녀 등 상속인 범위를 한 번만 입력합니다. 30초면 끝납니다." },
  { n: "03", title: "대화로 상담", body: "궁금한 것을 편하게 물어보면 담당 영역별로 안내가 이어집니다." },
  { n: "04", title: "할 일·일정 정리", body: "지금 해야 할 일과 기한을 체크리스트와 캘린더로 받습니다." },
];

/**
 * 상담 시작 = 새 탭. 현재 페이지(홈)를 유지한 채 상담을 별도 탭에서 진행한다.
 *
 * noopener/noreferrer를 일부러 안 붙인다 — 같은 오리진 내부 이동이라 그
 * 둘이 막는 "새 탭이 opener를 조작" 위험이 없고, 대신 opener 관계가 있어야
 * 비로그인 세션(scopedStorage, session_id·axis 등 sessionStorage 기반)이
 * 새 탭에 복제된다. noopener를 붙이면 이 복제가 끊겨 새 탭이 완전히 새
 * 세션으로 시작한다(실측 재현됨).
 */
function openConsult() {
  window.open("/onboarding/role", "_blank");
}

export function HomePage() {
  return (
    <>
      {/* ===== HERO ===== */}
      <section className="hero hero-photo">
        <div className="hero-bg-wrap" aria-hidden="true">
          <ParallaxImage
            src="/photos/kr-family-crossing.jpg"
            speed={0.16}
            position="center 74%"
          />
        </div>
        <div className="hero-inner">
          <p className="hero-tagline">가족의 다음을 쉽게 설계하다</p>
          <h1 className="hero-title">
            상속, 무엇부터 해야 할지{" "}
            <br className="hero-br" />
            순서대로 안내해 드립니다
          </h1>
          <p className="hero-lead">
            생전 자산 준비부터 사후 상속 절차와 상속세까지. 복잡한 제도와 기한을
            EZ-NEXT가 정리해 지금 해야 할 일 하나부터 알려드립니다.
          </p>
          <div className="hero-actions">
            <button
              type="button"
              className="btn btn-gold btn-lg"
              onClick={openConsult}
            >
              무료로 상담 시작
            </button>
            <Link to="/guide" className="btn btn-outline btn-lg btn-on-dark">
              상속 절차 먼저 보기
            </Link>
          </div>
          <p className="hero-note">
            회원가입 없이 바로 이용할 수 있습니다. 상담 기록을 저장하려면 로그인하세요.
          </p>
        </div>
      </section>

      {/* ===== 서비스 소개 ===== */}
      <section className="site-section" id="service">
        <div className="section-inner">
          <Reveal className="section-head">
            <Eyebrow>서비스 소개</Eyebrow>
            <h2>한 번 등록하면, 네 가지 영역이 이어집니다</h2>
            <p className="section-lead">
              가족관계를 한 번 입력하면 절차 안내·상속분 분석·유언 점검·상속세 시산에
              같은 정보를 재사용합니다. 같은 질문을 반복하지 않습니다.
            </p>
          </Reveal>
          <div className="feature-grid">
            {FEATURES.map((f, i) => (
              <Reveal as="article" key={f.title} className="feature-card" delay={i * 60}>
                <span className="feature-icon" aria-hidden="true">
                  {f.icon}
                </span>
                <h3>{f.title}</h3>
                <p>{f.body}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <PhotoBand
        src="/photos/kr-father-riverside.jpg"
        alt="아이를 안고 강가를 바라보는 사람"
        position="center 55%"
        caption="혼자 하기 어려운 일을, 순서대로 함께 정리합니다."
      />

      {/* ===== 이용 절차 ===== */}
      <section className="site-section alt">
        <div className="section-inner">
          <Reveal className="section-head">
            <Eyebrow>이용 절차</Eyebrow>
            <h2>네 단계로 시작합니다</h2>
          </Reveal>
          <ol className="usage-steps">
            {STEPS.map((s, i) => (
              <Reveal as="li" key={s.n} delay={i * 60}>
                <span className="usage-step-n">{s.n}</span>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      {/* ===== 상속 절차 미리보기 ===== */}
      <section className="site-section">
        <div className="section-inner">
          <Reveal className="section-head">
            <Eyebrow>상속 절차 안내</Eyebrow>
            <h2>사망 이후, 기한이 정해진 일들</h2>
            <p className="section-lead">
              아래는 대표적인 절차와 기한입니다. 개별 사안에 따라 달라질 수 있으며,
              자세한 내용은 안내 페이지에서 확인하세요.
            </p>
          </Reveal>
          <ul className="procedure-preview">
            {POST_DEATH_STEPS.slice(0, 4).map((step, i) => (
              <Reveal as="li" key={step.order} delay={i * 50}>
                <span className="procedure-order">{step.order}</span>
                <div className="procedure-body">
                  <h3>{step.title}</h3>
                  <span className="procedure-deadline">{step.deadline}</span>
                  <p>{step.detail}</p>
                </div>
              </Reveal>
            ))}
          </ul>
          <Link to="/guide" className="section-more">
            상속 절차 전체 보기 →
          </Link>
        </div>
      </section>

      {/* ===== 신뢰 / 개인정보 ===== */}
      <section className="site-section alt">
        <div className="section-inner">
          <Reveal className="section-head">
            <Eyebrow>믿고 맡기실 수 있도록</Eyebrow>
            <h2>세 가지 원칙</h2>
          </Reveal>
          <div className="trust-grid">
            <Reveal className="trust-item">
              <h3>원문은 저장하지 않습니다</h3>
              <p>
                유언장 등 민감한 원문은 점검에만 사용하고 저장하지 않습니다.
                주민등록번호 같은 민감정보가 입력되면 자동으로 지웁니다.
              </p>
            </Reveal>
            <Reveal className="trust-item" delay={70}>
              <h3>단정하지 않습니다</h3>
              <p>
                유효·무효, 소송 승패를 단정하지 않습니다. 법원이 판단해 온 사례에
                비추어 확인 결과만 보여드리고, 전문가 확인이 필요한 부분을 분명히
                안내합니다.
              </p>
            </Reveal>
            <Reveal className="trust-item" delay={140}>
              <h3>제도와 사람을 잇습니다</h3>
              <p>
                안심상속 원스톱, 대한법률구조공단 132 등 공식 창구로 이어지도록
                안내합니다. EZ-NEXT는 그 사이의 길잡이입니다.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ===== 관련 기관 ===== */}
      <section className="site-section">
        <div className="section-inner">
          <Reveal className="section-head">
            <Eyebrow>관련 기관 안내</Eyebrow>
            <h2>공식 창구</h2>
          </Reveal>
          <div className="agency-grid">
            {AGENCIES.map((a, i) => (
              <Reveal as="article" key={a.name} delay={i * 50}>
                <a
                  href={a.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="agency-card"
                >
                  <h3>{a.name}</h3>
                  <p>{a.desc}</p>
                  <span className="agency-contact">{a.contact}</span>
                </a>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ===== CTA ===== */}
      <section className="cta-band cta-band-photo">
        <div className="cta-band-bg-wrap" aria-hidden="true">
          <ParallaxImage
            src="/photos/kr-father-riverside.jpg"
            speed={0.14}
            position="center 58%"
          />
        </div>
        <div className="cta-band-inner">
          <h2>지금, 해야 할 일 하나부터 확인하세요</h2>
          <p>가족관계만 입력하면 나머지는 EZ-NEXT가 순서대로 안내합니다.</p>
          <button
            type="button"
            className="btn btn-gold btn-lg"
            onClick={openConsult}
          >
            무료로 상담 시작
          </button>
        </div>
      </section>
    </>
  );
}
