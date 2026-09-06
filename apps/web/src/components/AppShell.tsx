import { useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import { useApp } from "../lib/appState";
import { useFamilyGraphSync } from "../lib/useFamilyGraph";
import { AppHeader } from "./AppHeader";
import { ContextPanel } from "./ContextPanel";
import { FamilyGraphPanel } from "./FamilyGraphPanel";
import { SchedulePanel } from "./SchedulePanel";
import { Disclaimer } from "./ui";

type AppTheme = "dark" | "light";
const THEME_KEY = "eznext.app_theme";

function readTheme(): AppTheme {
  try {
    return window.localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

/**
 * 3-zone 셸: 상단 헤더 / 좌 본문(주) / 우 컨텍스트 패널 / 하단 고지.
 * 상담 앱 전용 스킨(금색 · 어두운/밝은 두 버전)을 data-app-theme 로 토글.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { familyGraphId, setFamilyGraphId, setFamilyGraph, plan } = useApp();
  const [familyPanelOpen, setFamilyPanelOpen] = useState(false);
  const [panelExpanded, setPanelExpanded] = useState(false);
  const [theme, setTheme] = useState<AppTheme>(readTheme);

  useFamilyGraphSync();

  useEffect(() => {
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  // 상담 앱 안에서는 앱 토글이 팔레트의 유일한 기준이다 — 이 값을 <html>에
  // 심어 tokens.css가 OS(prefers-color-scheme)와 무관하게 따라오게 한다.
  // (안 심으면 OS=다크 + 앱=밝게일 때 배경만 어두워지는 반쪽 상태가 된다.)
  // 첫 페인트 전에 적용해 깜빡임을 막는다.
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    return () => {
      // 셸을 벗어나면(공개 사이트) OS 설정을 다시 따르도록 되돌린다.
      root.removeAttribute("data-theme");
    };
  }, [theme]);

  return (
    <div className="app-shell" data-app-theme={theme}>
      <a className="skip-link" href="#main">
        본문 바로가기
      </a>
      <AppHeader
        theme={theme}
        onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
      />

      <div className={`app-body${plan ? " has-schedule" : ""}`}>
        <button
          type="button"
          className="context-panel-toggle"
          aria-expanded={panelExpanded}
          onClick={() => setPanelExpanded((v) => !v)}
        >
          준비 현황 {panelExpanded ? "접기 ▲" : "펼치기 ▼"}
        </button>

        {plan && (
          <div className="schedule-panel-wrap">
            <SchedulePanel />
          </div>
        )}

        <main id="main" className="app-main">
          {children}
        </main>

        <div className={`context-panel-wrap${panelExpanded ? " expanded" : ""}`}>
          <ContextPanel onEditFamily={() => setFamilyPanelOpen(true)} />
        </div>
      </div>

      <Disclaimer variant="global" />

      {familyPanelOpen && (
        <FamilyGraphPanel
          familyGraphId={familyGraphId}
          onFamilyGraphIdChange={(id) => setFamilyGraphId(id)}
          onGraphChange={(g) => setFamilyGraph(g)}
          onClose={() => setFamilyPanelOpen(false)}
        />
      )}
    </div>
  );
}
