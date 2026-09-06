import { chromium } from "playwright";
const OUT = process.env.SHOT_DIR || "_mock/_shots"; // apps/web 기준 상대경로. 다른 곳에 저장하려면 SHOT_DIR 지정
const BASE = process.argv[2] || "http://localhost:5174";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1.5 });
await p.addInitScript(() => { try { sessionStorage.setItem("eznext.consult_axis", "pre_need"); localStorage.setItem("eznext.app_theme", "light"); } catch {} });
await p.goto(`${BASE}/chat`, { waitUntil: "networkidle" });
await p.waitForTimeout(500);

async function say(t) {
  await p.locator(".composer-input").fill(t);
  await p.getByRole("button", { name: "보내기" }).click();
  // wait for the thinking indicator to disappear
  await p.waitForTimeout(800);
  await p.locator(".agent-thinking").waitFor({ state: "detached", timeout: 30000 }).catch(() => {});
  await p.waitForTimeout(500);
}

await say("재산을 정리하고 싶어요");
await say("예금 8천만원, 부동산 5억이요");
await say("대출 2천만원 있어요");
await say("나머지는 없어요");
await p.waitForTimeout(1000);
await p.screenshot({ path: `${OUT}/real-card-laptop.png`, fullPage: false });
await p.screenshot({ path: `${OUT}/real-card-full.png`, fullPage: true });
console.log("ok");
await b.close();
