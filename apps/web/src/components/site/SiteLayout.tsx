import { useEffect } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

/** 마케팅/안내 사이트 셸: 상단 내비 + 본문 + 푸터 + 상시 상담 시작 버튼. */
export function SiteLayout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [pathname]);

  return (
    <div className="site">
      <a className="skip-link" href="#site-main">
        본문 바로가기
      </a>
      <SiteHeader />
      <main id="site-main" className="site-main">
        <Outlet />
      </main>
      <SiteFooter />

      <button
        type="button"
        className="floating-cta"
        onClick={() => navigate("/onboarding/role")}
      >
        상담 시작
      </button>
    </div>
  );
}
