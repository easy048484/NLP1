import { useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export default function App() {
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState<string | null>(null);

  const send = async () => {
    const res = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: "local-dev", user_message: message }),
    });
    const data = await res.json();
    setReply(data.reply);
  };

  return (
    <main style={{ maxWidth: 480, margin: "0 auto", padding: 16, fontFamily: "sans-serif" }}>
      <h1>가족 자산 준비</h1>
      <p>오케스트레이터 뼈대 연결 확인용 최소 화면입니다.</p>
      <input
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="메시지를 입력하세요"
        style={{ width: "100%", padding: 8 }}
      />
      <button onClick={send} style={{ marginTop: 8 }}>
        보내기
      </button>
      {reply && <p style={{ marginTop: 16 }}>{reply}</p>}
    </main>
  );
}
