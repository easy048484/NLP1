import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useApp } from "../lib/appState";
import { useFamilyGraphSync } from "../lib/useFamilyGraph";
import { AppHeader } from "./AppHeader";
import { ContextPanel } from "./ContextPanel";
import { FamilyGraphPanel } from "./FamilyGraphPanel";
import { Disclaimer } from "./ui";

const DevModeContext = createContext(false);
// eslint-disable-next-line react-refresh/only-export-components
export function useDevMode(): boolean {
  return useContext(DevModeContext);
}

type AppTheme = "dark" | "light";
const THEME_KEY = "eznext.app_theme";

function readTheme(): AppTheme {
  try {
    return window.localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

/**
 * 3-zone 셸: 상단 헤더 / 좌 본문(주) / 우 컨텍스트 패널 / 하단 고지.
 * 상담 앱 전용 스킨(금색 · 어두운/밝은 두 버전)을 data-app-theme 로 토글.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { familyGraphId, setFamilyGraphId, setFamilyGraph } = useApp();
  const [devMode, setDevMode] = useState(false);
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

  return (
    <DevModeContext.Provider value={devMode}>
      <div className="app-shell" data-app-theme={theme}>
        <a className="skip-link" href="#main">
          본문 바로가기
        </a>
        <AppHeader
          devMode={devMode}
          onToggleDev={() => setDevMode((v) => !v)}
          theme={theme}
          onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
        />

        <div className="app-body">
          <button
            type="button"
            className="context-panel-toggle"
            aria-expanded={panelExpanded}
            onClick={() => setPanelExpanded((v) => !v)}
          >
            준비 현황 {panelExpanded ? "접기 ▲" : "펼치기 ▼"}
          </button>

          <div className={`context-panel-wrap${panelExpanded ? " expanded" : ""}`}>
            <ContextPanel onEditFamily={() => setFamilyPanelOpen(true)} />
          </div>

          <main id="main" className="app-main">
            {children}
          </main>
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
    </DevModeContext.Provider>
  );
}
