import { useState } from "react";
import { Link } from "react-router-dom";
import { FAQ_ITEMS } from "../../lib/content";
import { PageHero } from "../../components/site/PageHero";

export function FaqPage() {
  const [open, setOpen] = useState<number | null>(0);

  return (
    <>
      <PageHero
        eyebrow="자주 묻는 질문"
        title="궁금한 점을 모았습니다"
        photo="/photos/kr-family-crossing.jpg"
        lead={
          <>
            더 자세한 절차는 <Link to="/guide">상속 절차 안내</Link>에서 확인하실 수
            있습니다.
          </>
        }
      />

      <section className="site-section">
        <div className="section-inner section-narrow">
          <ul className="faq-list">
            {FAQ_ITEMS.map((item, i) => (
              <li key={item.q} className={`faq-item${open === i ? " open" : ""}`}>
                <button
                  type="button"
                  className="faq-q"
                  aria-expanded={open === i}
                  onClick={() => setOpen(open === i ? null : i)}
                >
                  <span>{item.q}</span>
                  <span className="faq-toggle" aria-hidden="true">
                    {open === i ? "−" : "+"}
                  </span>
                </button>
                {open === i && <p className="faq-a">{item.a}</p>}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="cta-band">
        <div className="section-inner">
          <h2>답을 찾지 못하셨나요?</h2>
          <p>상담을 시작하면 상황에 맞는 안내를 받으실 수 있습니다.</p>
          <Link to="/onboarding/role" className="btn btn-gold btn-lg">
            상담 시작
          </Link>
        </div>
      </section>
    </>
  );
}
