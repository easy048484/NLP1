import { Link } from "react-router-dom";
import { POST_DEATH_STEPS, WILL_METHODS } from "../../lib/content";
import { Disclaimer } from "../../components/ui";
import { PageHero } from "../../components/site/PageHero";

/** 상속 절차 안내 — 정보 페이지. */
export function GuidePage() {
  return (
    <>
      <PageHero
        eyebrow="상속 절차 안내"
        title="상속, 이런 순서로 진행됩니다"
        photo="/photos/kr-family-crossing.jpg"
        lead="사망 이후 상속인이 밟게 되는 대표적인 절차와 기한을 정리했습니다. 아래 내용은 일반적인 안내이며, 개별 사안에 따라 달라질 수 있습니다."
      />

      <section className="site-section">
        <div className="section-inner section-narrow">
          <h2 className="guide-h2">사후 절차 타임라인</h2>
          <ol className="guide-timeline">
            {POST_DEATH_STEPS.map((step) => (
              <li key={step.order}>
                <div className="guide-timeline-marker">
                  <span>{step.order}</span>
                </div>
                <div className="guide-timeline-body">
                  <h3>{step.title}</h3>
                  <dl className="guide-meta">
                    <div>
                      <dt>기한</dt>
                      <dd>{step.deadline}</dd>
                    </div>
                    <div>
                      <dt>어디서</dt>
                      <dd>{step.where}</dd>
                    </div>
                  </dl>
                  <p>{step.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="site-section alt">
        <div className="section-inner section-narrow">
          <h2 className="guide-h2">법정상속분과 유류분</h2>
          <div className="info-block">
            <h3>상속 순위 (민법 제1000조)</h3>
            <ol className="info-list">
              <li>1순위 — 직계비속(자녀·손자녀)과 배우자</li>
              <li>2순위 — 직계존속(부모·조부모)과 배우자</li>
              <li>3순위 — 형제자매</li>
              <li>4순위 — 4촌 이내의 방계혈족</li>
            </ol>
            <p className="info-note">
              배우자는 1·2순위 상속인과 공동으로 상속하며, 1·2순위가 없으면 단독
              상속합니다.
            </p>
          </div>
          <div className="info-block">
            <h3>법정상속분</h3>
            <p>
              같은 순위의 상속인은 균등하게 나누고, 배우자는 다른 상속인보다 5할을
              더 받습니다(1.5 : 1). 예를 들어 배우자와 자녀 2명이면 1.5 : 1 : 1의
              비율입니다.
            </p>
          </div>
          <div className="info-block">
            <h3>유류분</h3>
            <p>
              유언으로 특정인에게 재산이 치우쳐도, 일정 상속인은 최소한의 몫(유류분)을
              주장할 수 있습니다. 직계비속·배우자는 법정상속분의 1/2, 직계존속은
              1/3입니다. 형제자매의 유류분 규정은 2024년 헌법재판소 결정으로 효력을
              잃었습니다.
            </p>
          </div>
        </div>
      </section>

      <section className="site-section">
        <div className="section-inner section-narrow">
          <h2 className="guide-h2">유언의 방식 (민법 제1065조~)</h2>
          <div className="will-grid">
            {WILL_METHODS.map((w) => (
              <div key={w.name} className="will-card">
                <h3>{w.name}</h3>
                <p>{w.summary}</p>
              </div>
            ))}
          </div>
          <div className="info-block">
            <h3>자필증서 유언의 형식 요건 (민법 제1066조)</h3>
            <p>
              전문(全文)을 직접 쓰고, <strong>작성 연월일 · 주소 · 성명</strong>을 적은
              뒤 <strong>날인</strong>해야 합니다. 한 가지라도 빠지면 무효로 판단한
              판례가 있습니다. EZ-NEXT의 유언 요건 점검으로 항목별로 확인할 수 있습니다.
            </p>
          </div>
        </div>
      </section>

      <section className="site-section alt">
        <div className="section-inner section-narrow">
          <h2 className="guide-h2">상속세의 큰 흐름</h2>
          <ol className="info-list info-list-flow">
            <li>상속재산가액에서 채무·공과금·장례비를 뺍니다.</li>
            <li>일괄공제(5억 원) 또는 기초공제+인적공제 중 큰 금액을 공제합니다.</li>
            <li>배우자 상속공제, 금융재산 상속공제 등을 추가로 적용합니다.</li>
            <li>과세표준에 세율(10~50%)을 적용해 산출세액을 계산합니다.</li>
            <li>신고세액공제를 반영해 최종 납부세액을 확정합니다.</li>
          </ol>
          <p className="info-note">
            신고·납부 기한은 상속개시일이 속한 달의 말일부터 6개월 이내(비거주자는
            9개월)입니다. 분납·연부연납 제도를 활용할 수 있습니다.
          </p>
        </div>
      </section>

      <section className="site-section">
        <div className="section-inner section-narrow guide-cta">
          <h2 className="guide-h2">내 상황에 맞는 안내가 필요하다면</h2>
          <p>가족관계를 입력하면 위 절차 중 지금 해야 할 일부터 정리해 드립니다.</p>
          <Link to="/onboarding/role" className="btn btn-primary btn-lg">
            상담 시작
          </Link>
          <Disclaimer variant="inline">
            이 페이지의 정보는 일반적인 안내이며 법률·세무 자문이 아닙니다. 정확한
            판단은 대한법률구조공단(132), 국세상담센터(126) 등 관계 기관과 전문가
            확인이 필요합니다.
          </Disclaimer>
        </div>
      </section>
    </>
  );
}
