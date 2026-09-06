import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.resolve(__dirname, "../src/lib/__fixtures__/responses");

function loadFixture(name) {
  const p = path.join(FIX, name.endsWith(".json") ? name : `${name}.json`);
  const d = JSON.parse(fs.readFileSync(p, "utf8"));
  return d.response ?? d;
}

const PORT = process.env.MOCK_PORT ? Number(process.env.MOCK_PORT) : 8787;

const server = http.createServer((req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "*");
  res.setHeader("Access-Control-Allow-Methods", "*");
  if (req.method === "OPTIONS") { res.writeHead(204); return res.end(); }

  if (req.method === "POST" && req.url === "/chat") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      let msg = "";
      try { msg = JSON.parse(body).user_message ?? ""; } catch {}
      // user_message 안에 fixture 이름을 그대로 넣어 보낸다: "fixture:demo-final/T4"
      const m = msg.match(/fixture:([\w\-./가-힣]+)/);
      const name = m ? m[1] : "demo-final/T4";
      try {
        const payload = loadFixture(name);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify(payload));
      } catch (e) {
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ detail: String(e) }));
      }
    });
    return;
  }

  // 세션 복원·가족그래프 조회 등은 전부 비어있게
  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ detail: "mock: not found" }));
});

server.listen(PORT, () => console.log(`mock api on http://localhost:${PORT}`));
