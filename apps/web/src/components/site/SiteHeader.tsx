import { useEffect, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useApp } from "../../lib/appState";
import { Wordmark } from "../ui";

const NAV = [
  { to: "/service", label: "서비스 소개" },
  { to: "/guide", label: "상속 절차 안내" },
  { to: "/faq", label: "자주 묻는 질문" },
];

/** 상조·금융기관 홈페이지 형식의 상단 네비게이션 (유틸리티 바 + 메인 내비). */
export function SiteHeader() {
  const { auth, logout } = useApp();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  return (
    <header className="site-header">
      <div className="site-utility">
        <div className="site-utility-inner">
          <span className="site-utility-text">법률상담 국번없이 132</span>
          <span className="site-utility-sep" aria-hidden="true">
            ·
          </span>
          {auth ? (
            <>
              <span className="site-utility-user">{auth.user.name} 님</span>
              <button type="button" className="site-utility-link" onClick={logout}>
                로그아웃
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="site-utility-link">
                로그인
              </Link>
              <span className="site-utility-sep" aria-hidden="true">
                ·
              </span>
              <Link to="/signup" className="site-utility-link">
                회원가입
              </Link>
            </>
          )}
        </div>
      </div>

      <div className="site-nav-bar">
        <div className="site-nav-inner">
          <Link to="/" className="site-logo" aria-label="EZNEXT 홈">
            <Wordmark size="sm" />
          </Link>

          <button
            type="button"
            className="site-nav-toggle"
            aria-expanded={menuOpen}
            aria-label="메뉴 열기"
            onClick={() => setMenuOpen((v) => !v)}
          >
            <span />
            <span />
            <span />
          </button>

          <nav className={`site-nav${menuOpen ? " open" : ""}`} aria-label="주요 메뉴">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `site-nav-link${isActive ? " active" : ""}`
                }
              >
                {item.label}
              </NavLink>
            ))}
            <button
              type="button"
              className="btn btn-primary site-nav-cta"
              onClick={() => navigate("/onboarding/role")}
            >
              상담 시작
            </button>
          </nav>
        </div>
      </div>
    </header>
  );
}
