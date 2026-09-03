import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

/** 상담 시작 = 새 탭. 현재 페이지를 유지한 채 상담을 별도 탭에서 진행한다. */
function openConsult() {
  window.open("/onboarding/role", "_blank", "noopener,noreferrer");
}

/** 마케팅/안내 사이트 셸: 상단 내비 + 본문 + 푸터 + 상시 상담 시작 버튼. */
export function SiteLayout() {
  const { pathname } = useLocation();

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
        onClick={openConsult}
      >
        상담 시작
      </button>
    </div>
  );
}
