import { chromium } from "playwright";
const OUT = process.env.SHOT_DIR || "_mock/_shots"; // apps/web 기준 상대경로. 다른 곳에 저장하려면 SHOT_DIR 지정
const b = await chromium.launch();

// 1) family children step (건너뛰기/입력완료)
{
  const p = await b.newPage({ viewport: { width: 900, height: 1000 }, deviceScaleFactor: 2 });
  await p.addInitScript(() => { try { sessionStorage.setItem("eznext.consult_axis", "pre_need"); } catch {} });
  await p.goto("http://localhost:5173/onboarding/family", { waitUntil: "networkidle" });
  await p.waitForTimeout(400);
  await p.getByRole("button", { name: "배우자 없음" }).click();
  await p.waitForTimeout(300);
  await p.locator(".intake-panel").screenshot({ path: `${OUT}/verify-family.png` });
  await p.close();
}
// 2) amount card, light + dark
for (const theme of ["light", "dark"]) {
  const p = await b.newPage({ viewport: { width: 1280, height: 850 }, deviceScaleFactor: 1.5 });
  await p.addInitScript((t) => { try { sessionStorage.setItem("eznext.consult_axis", "pre_need"); localStorage.setItem("eznext.app_theme", t); } catch {} }, theme);
  await p.goto("http://localhost:5173/chat", { waitUntil: "networkidle" });
  await p.waitForTimeout(400);
  await p.locator(".composer-input").fill("fixture:demo-final/T4");
  await p.getByRole("button", { name: "보내기" }).click();
  await p.waitForTimeout(1200);
  await p.screenshot({ path: `${OUT}/verify-card-${theme}.png` });
  await p.close();
}
console.log("ok");
await b.close();
