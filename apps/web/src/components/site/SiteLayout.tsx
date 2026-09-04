import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

/**
 * 상담 시작 = 새 탭. noopener를 안 붙이는 이유는 HomePage.tsx의 openConsult
 * 주석 참고 — 비로그인 세션(sessionStorage 기반) 복제를 위해 opener 관계를
 * 유지해야 한다.
 */
function openConsult() {
  window.open("/onboarding/role", "_blank");
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
