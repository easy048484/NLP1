import { Link, useNavigate } from "react-router-dom";
import { PageHero } from "../../components/site/PageHero";

const AGENTS = [
  {
    name: "상속 절차 안내",
    body: "사망신고부터 상속세 신고까지, 기한이 정해진 일을 순서대로 안내하고 '나의 할 일' 체크리스트와 캘린더(.ics)로 정리합니다.",
  },
  {
    name: "법정상속분 · 유류분 분석",
    body: "등록된 가족을 기준으로 법정상속분과 유류분을 계산하고, 유류분 격차와 참고할 만한 사례를 보여드립니다. 소송 승패는 예측하지 않습니다.",
  },
  {
    name: "유언 요건 점검",
    body: "자필증서·녹음 유언의 형식 요건을 항목별로 확인합니다. 색은 판례가 판단해 온 방향을 뜻하며, 유효·무효를 단정하지 않습니다.",
  },
  {
    name: "예상 상속세 시산",
    body: "재산·채무와 공제를 반영해 예상 세액을 단계적으로 계산합니다. 등록된 가족 정보를 재사용하므로 배우자·자녀를 다시 묻지 않습니다.",
  },
  {
    name: "생전 자산 정리",
    body: "예금·보험·부동산·연금을 정리하고 은퇴자금 갭을 추정합니다. 이 정보는 유언·상속세 상담에 그대로 이어집니다.",
  },
];

export function ServicePage() {
  const navigate = useNavigate();
  return (
    <>
      <PageHero
        eyebrow="서비스 소개"
        title="흩어진 상속 준비를 한 곳에서"
        photo="/photos/kr-father-riverside.jpg"
        lead="EZNEXT는 생전 준비와 사후 절차를 잇는 대화형 안내 서비스입니다. 제도와 기한은 복잡하지만, 지금 해야 할 일은 하나씩입니다."
      />

      <section className="site-section">
        <div className="section-inner section-narrow">
          <h2 className="guide-h2">이런 분께 도움이 됩니다</h2>
          <ul className="info-list">
            <li>가족을 떠나보낸 뒤 무엇부터 해야 할지 막막한 분</li>
            <li>상속포기·한정승인 기한이 지나기 전에 판단이 필요한 분</li>
            <li>상속세가 얼마나 나올지 미리 가늠하고 싶은 분</li>
            <li>유언장을 남기려는데 형식이 맞는지 확인하고 싶은 분</li>
            <li>은퇴를 앞두고 자산을 정리하고 가족에게 남길 준비를 하려는 분</li>
          </ul>
        </div>
      </section>

      <section className="site-section alt">
        <div className="section-inner section-narrow">
          <h2 className="guide-h2">담당 영역</h2>
          <div className="agent-detail-list">
            {AGENTS.map((a) => (
              <div key={a.name} className="agent-detail">
                <h3>{a.name}</h3>
                <p>{a.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="site-section">
        <div className="section-inner section-narrow">
          <h2 className="guide-h2">한 번 입력, 계속 재사용</h2>
          <p className="info-note">
            가족관계와 자산 정보를 한 번 등록하면 절차 안내·상속분 분석·유언 점검·
            상속세 시산이 그 정보를 공유합니다. 상담을 옮겨 다녀도 같은 질문을
            반복하지 않습니다. 여러 답변이 필요한 질문은 각 영역의 근거를 카드로
            나누어 보여드리고, 확인이 더 필요한 숫자에는 '확인 필요' 표시를 붙입니다.
          </p>
        </div>
      </section>

      <section className="cta-band">
        <div className="section-inner">
          <h2>지금 시작해 보세요</h2>
          <p>회원가입 없이 바로 이용할 수 있습니다.</p>
          <div className="hero-actions">
            <button
              type="button"
              className="btn btn-gold btn-lg"
              onClick={() => navigate("/onboarding/role")}
            >
              상담 시작
            </button>
            <Link to="/guide" className="btn btn-outline btn-lg btn-on-dark">
              상속 절차 안내 보기
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
