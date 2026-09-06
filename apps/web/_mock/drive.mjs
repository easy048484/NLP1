import { chromium } from "playwright";
const OUT = process.env.SHOT_DIR || "_mock/_shots"; // apps/web 기준 상대경로. 다른 곳에 저장하려면 SHOT_DIR 지정
const tag = process.argv[2] || "before";
const browser = await chromium.launch();

const CASES = [
  { fx: "demo-final/T4", label: "asset-inventory" },
  { fx: "demo-final/T5", label: "heir-shares" },
  { fx: "demo-final/T6", label: "heir-shares2" },
  { fx: "S-2", label: "tax" },
];
const VIEWPORTS = [
  { w: 1440, h: 900, name: "desktop" },
  { w: 1100, h: 800, name: "laptop" },
  { w: 768, h: 900, name: "tablet" },
  { w: 390, h: 844, name: "mobile" },
];

for (const theme of ["light", "dark"]) {
  for (const vp of VIEWPORTS) {
    for (const c of CASES) {
      const page = await browser.newPage({
        viewport: { width: vp.w, height: vp.h },
        deviceScaleFactor: 1.5,
      });
      await page.addInitScript((t) => {
        try {
          sessionStorage.setItem("eznext.consult_axis", "pre_need");
          localStorage.setItem("eznext.app_theme", t);
        } catch {}
      }, theme);
      await page.goto("http://localhost:5173/chat", { waitUntil: "networkidle" });
      await page.waitForTimeout(400);
      const input = page.locator(".composer-input");
      await input.fill(`fixture:${c.fx}`);
      await page.getByRole("button", { name: "보내기" }).click();
      await page.waitForTimeout(1200);
      // full page + a clipped "viewport only" shot to see truncation as a user would
      await page.screenshot({ path: `${OUT}/card-${tag}-${theme}-${vp.name}-${c.label}.png`, fullPage: false });
      if (vp.name === "desktop" || vp.name === "mobile") {
        await page.screenshot({ path: `${OUT}/cardFULL-${tag}-${theme}-${vp.name}-${c.label}.png`, fullPage: true });
      }
      await page.close();
    }
  }
}
console.log("done " + tag);
await browser.close();
