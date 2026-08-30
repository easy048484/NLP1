import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { SiteLayout } from "./components/site/SiteLayout";
import { AuthScreen } from "./screens/AuthScreen";
import { ChatScreen } from "./screens/ChatScreen";
import { FamilyScreen } from "./screens/FamilyScreen";
import { HomeScreen } from "./screens/HomeScreen";
import { RoleScreen } from "./screens/RoleScreen";
import { FaqPage } from "./screens/site/FaqPage";
import { GuidePage } from "./screens/site/GuidePage";
import { HomePage } from "./screens/site/HomePage";
import { ServicePage } from "./screens/site/ServicePage";

function ShellLayout() {
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

export default function App() {
  return (
    <Routes>
      {/* 공개 사이트 (상조·금융기관 홈페이지 형식) */}
      <Route element={<SiteLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/service" element={<ServicePage />} />
        <Route path="/guide" element={<GuidePage />} />
        <Route path="/faq" element={<FaqPage />} />
      </Route>

      {/* 계정 — 버튼으로 진입할 때만 */}
      <Route path="/login" element={<AuthScreen mode="login" />} />
      <Route path="/signup" element={<AuthScreen mode="signup" />} />

      {/* 상담 온보딩 */}
      <Route path="/onboarding/role" element={<RoleScreen />} />
      <Route path="/onboarding/family" element={<FamilyScreen />} />

      {/* 상담 앱 (3-zone 셸) */}
      <Route element={<ShellLayout />}>
        <Route path="/home" element={<HomeScreen />} />
        <Route path="/chat" element={<ChatScreen />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
