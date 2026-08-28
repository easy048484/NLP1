import { useState } from "react";
import { ChatEntryScreen, ChatScreen } from "./ChatScreens";
import { IntakeScreen, HomeScreen } from "./IntakeHomeScreens";
import { LoginScreen, RoleScreen, SignupScreen } from "./AuthScreens";
import { SCREENS, type ScreenId } from "./screens";
import { TaxWizardScreen, WillCheckScreen } from "./TaxWillScreens";

export default function App() {
  const [current, setCurrent] = useState<ScreenId>("login");
  const index = SCREENS.findIndex((s) => s.id === current);

  const go = (id: ScreenId) => setCurrent(id);
  const shift = (delta: number) => {
    const next = SCREENS[(index + delta + SCREENS.length) % SCREENS.length];
    setCurrent(next.id);
  };

  return (
    <div className="studio">
      <aside className="studio-nav">
        <div className="studio-kicker">Design study</div>
        <h1>가문</h1>
        <p>
          상조·금융 앱 톤의 화면 예시입니다. 실제 서비스와 분리되어 있으며 API는
          붙지 않습니다.
        </p>
        {SCREENS.map((screen) => (
          <button
            key={screen.id}
            type="button"
            className={`studio-item${current === screen.id ? " studio-item-on" : ""}`}
            onClick={() => go(screen.id)}
          >
            <span className="studio-num">{screen.n}</span>
            <span>
              <strong>{screen.title}</strong>
              <span>{screen.hint}</span>
            </span>
          </button>
        ))}
      </aside>

      <main className="studio-stage">
        <div className="phone">{renderScreen(current, go)}</div>
        <div className="stage-actions">
          <button type="button" className="ghost-btn" onClick={() => shift(-1)}>
            이전 화면
          </button>
          <button type="button" className="primary-btn" onClick={() => shift(1)}>
            다음 화면 ({index + 1}/9)
          </button>
        </div>
      </main>
    </div>
  );
}

function renderScreen(id: ScreenId, go: (id: ScreenId) => void) {
  switch (id) {
    case "login":
      return <LoginScreen onSignup={() => go("signup")} onNext={() => go("role")} />;
    case "signup":
      return <SignupScreen onLogin={() => go("login")} onNext={() => go("role")} />;
    case "role":
      return <RoleScreen onNext={() => go("intake")} />;
    case "intake":
      return <IntakeScreen onNext={() => go("home")} />;
    case "home":
      return (
        <HomeScreen
          onChat={() => go("chat-entry")}
          onTax={() => go("tax")}
          onWill={() => go("will")}
        />
      );
    case "chat-entry":
      return <ChatEntryScreen onChat={() => go("chat")} />;
    case "chat":
      return <ChatScreen />;
    case "tax":
      return <TaxWizardScreen />;
    case "will":
      return <WillCheckScreen />;
  }
}
