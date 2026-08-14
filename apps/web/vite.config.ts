import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  // 저장소 루트의 .env를 그대로 읽습니다 (README의 "루트 .env 하나만 관리" 방침과 일치).
  // 백엔드에 노출되지 않는 값이라도 Vite는 VITE_ 접두사가 붙은 키만 클라이언트로 넘기므로 안전합니다.
  envDir: path.resolve(__dirname, "../.."),
});
