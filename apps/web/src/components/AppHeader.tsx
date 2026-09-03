import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../lib/appState";
import { AXIS_LABEL } from "../lib/consult";
import type { ConsultAxis } from "../types";
import { Button, Dialog, Wordmark } from "./ui";

const OTHER_AXIS: Record<ConsultAxis, ConsultAxis> = {
  pre_need: "post_death",
  post_death: "pre_need",
};

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
  const { auth, axis, resetChat, switchAxis, logout } = useApp();
  const navigate = useNavigate();
  const [showAxisConfirm, setShowAxisConfirm] = useState(false);

  return (
    <header className="app-header">
      <button
        type="button"
        className="app-header-brand"
        onClick={() => navigate(axis ? "/home" : "/onboarding/role")}
        aria-label="EZ-NEXT 홈"
      >
        <Wordmark size="sm" />
      </button>

      <div className="app-header-actions">
        {axis && (
          <button
            type="button"
            className="app-header-axis"
            onClick={() => setShowAxisConfirm(true)}
            aria-label={`현재 ${AXIS_LABEL[axis]} 모드. 눌러서 전환`}
          >
            {AXIS_LABEL[axis]}
          </button>
        )}
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

      {showAxisConfirm && axis && (
        <Dialog
          title="상담 축을 전환할까요?"
          onClose={() => setShowAxisConfirm(false)}
          footer={
            <>
              <Button variant="outline" onClick={() => setShowAxisConfirm(false)}>
                취소
              </Button>
              <Button
                onClick={() => {
                  setShowAxisConfirm(false);
                  switchAxis(OTHER_AXIS[axis]);
                  navigate("/chat");
                }}
              >
                전환
              </Button>
            </>
          }
        >
          <p>
            {AXIS_LABEL[axis]} → {AXIS_LABEL[OTHER_AXIS[axis]]}(으)로 바꿉니다.
            <br />
            진행 중인 대화가 초기화됩니다. 등록된 가족관계는 그대로 유지됩니다.
          </p>
        </Dialog>
      )}
    </header>
  );
}
