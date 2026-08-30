import { Link } from "react-router-dom";
import { AGENCIES } from "../../lib/content";
import { Wordmark } from "../ui";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div className="site-footer-brand">
          <Wordmark size="sm" />
          <p>가족의 다음을 쉽게 설계하다</p>
        </div>

        <div className="site-footer-cols">
          <div className="site-footer-col">
            <h3>서비스</h3>
            <Link to="/service">서비스 소개</Link>
            <Link to="/guide">상속 절차 안내</Link>
            <Link to="/faq">자주 묻는 질문</Link>
            <Link to="/onboarding/role">상담 시작</Link>
          </div>
          <div className="site-footer-col">
            <h3>계정</h3>
            <Link to="/login">로그인</Link>
            <Link to="/signup">회원가입</Link>
          </div>
          <div className="site-footer-col site-footer-col-wide">
            <h3>관련 기관</h3>
            {AGENCIES.map((a) => (
              <a key={a.name} href={a.url} target="_blank" rel="noopener noreferrer">
                {a.name}
              </a>
            ))}
          </div>
        </div>
      </div>

      <div className="site-footer-legal">
        <p>
          EZNEXT가 제공하는 정보는 일반적인 안내이며 법률·세무 자문이 아닙니다.
          기한·요건은 개별 사안에 따라 달라질 수 있으므로 정확한 판단은 관계
          기관과 전문가 확인이 필요합니다. 유언장 등 민감한 원문은 저장하지
          않습니다.
        </p>
        <p className="site-footer-copy">
          © {new Date().getFullYear()} EZNEXT · 사진 제공 Unsplash
        </p>
      </div>
    </footer>
  );
}
