import { useNavigate } from "react-router-dom";
import { useApp } from "../lib/appState";
import { AXIS_LABEL } from "../lib/consult";
import { Wordmark } from "./ui";

export function AppHeader({
  devMode,
  onToggleDev,
  theme,
  onToggleTheme,
}: {
  devMode: boolean;
  onToggleDev: () => void;
  theme: "dark" | "light";
  onToggleTheme: () => void;
}) {
  const { auth, axis, resetChat, logout } = useApp();
  const navigate = useNavigate();

  return (
    <header className="app-header">
      <button
        type="button"
        className="app-header-brand"
        onClick={() => navigate(axis ? "/home" : "/onboarding/role")}
        aria-label="EZNEXT 홈"
      >
        <Wordmark size="sm" />
      </button>

      <div className="app-header-actions">
        {axis && <span className="app-header-axis">{AXIS_LABEL[axis]}</span>}
        <button
          type="button"
          className="app-header-btn"
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "밝은 화면으로" : "어두운 화면으로"}
        >
          {theme === "dark" ? "☀ 밝게" : "☾ 어둡게"}
        </button>
        <button
          type="button"
          className="app-header-btn"
          onClick={() => {
            resetChat();
            navigate("/chat");
          }}
        >
          새 상담
        </button>
        {auth ? (
          <>
            <span className="app-header-user">{auth.user.name} 님</span>
            <button type="button" className="app-header-btn" onClick={logout}>
              로그아웃
            </button>
          </>
        ) : (
          <button
            type="button"
            className="app-header-btn"
            onClick={() => navigate("/login")}
          >
            로그인
          </button>
        )}
        <button
          type="button"
          className={`app-header-btn dev-toggle${devMode ? " on" : ""}`}
          aria-pressed={devMode}
          onClick={onToggleDev}
        >
          {"</>"} 개발자
        </button>
      </div>
    </header>
  );
}
