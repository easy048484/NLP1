import { chromium } from "playwright";
const OUT = process.env.SHOT_DIR || "_mock/_shots"; // apps/web 기준 상대경로. 다른 곳에 저장하려면 SHOT_DIR 지정
const b = await chromium.launch();
for (const [theme, w, h, name] of [["light", 390, 844, "mobile"], ["dark", 1280, 800, "laptop"]]) {
  const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1.5 });
  await p.addInitScript((t) => { try { sessionStorage.setItem("eznext.consult_axis", "pre_need"); localStorage.setItem("eznext.app_theme", t); } catch {} }, theme);
  await p.goto("http://localhost:5173/chat", { waitUntil: "networkidle" });
  await p.waitForTimeout(400);
  await p.locator(".composer-input").fill("fixture:demo-final/T4");
  await p.getByRole("button", { name: "보내기" }).click();
  await p.waitForTimeout(1000);
  await p.screenshot({ path: `${OUT}/final-${theme}-${name}.png`, fullPage: name === "mobile" });
  await p.close();
}
await b.close();
console.log("ok");
