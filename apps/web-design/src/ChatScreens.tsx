import { Topbar } from "./Topbar";

export function ChatEntryScreen({ onChat }: { onChat: () => void }) {
  return (
    <div className="screen">
      <Topbar title="상담 창구" subtitle="원하시는 안내를 선택해 주십시오." />
      <div className="screen-scroll">
        <div className="auth-hero" style={{ paddingTop: 8 }}>
          <div className="gold-rule" />
          <h1 style={{ fontSize: 22 }}>어떤 도움을 드릴까요.</h1>
          <p>가족관계는 이미 등록되어 있습니다. 주제만 고르시면 해당 안내가 이어집니다.</p>
        </div>
        <div className="topic-grid">
          <button type="button" className="topic-card" onClick={onChat}>
            <h3>상속 절차</h3>
            <p>사망신고, 안심상속 원스톱, 한정승인·포기의 기한과 서류</p>
          </button>
          <button type="button" className="topic-card" onClick={onChat}>
            <h3>유언 요건 점검</h3>
            <p>자필증서·녹음 유언의 형식 요건을 항목별로 확인</p>
          </button>
          <button type="button" className="topic-card" onClick={onChat}>
            <h3>상속세 시산</h3>
            <p>등록된 가족을 반영해 재산·채무부터 계산</p>
          </button>
        </div>
      </div>
    </div>
  );
}

export function ChatScreen() {
  return (
    <div className="screen">
      <Topbar title="상담" subtitle="상속 절차 안내" />
      <div className="chat-scroll">
        <div className="msg-col">
          <div className="agent-label">절차 안내</div>
          <div className="bubble bubble-assistant">
            배우자 김은정 님, 자녀 김하준 님이 공동상속인으로 확인됩니다. 지금 기준으로
            챙기실 일을 정리했습니다.
          </div>
          <div className="result-card">
            <h4>기한 안내</h4>
            <ul>
              <li>한정승인·상속포기 — 상속개시 안 날부터 3개월</li>
              <li>상속세 신고 — 사망일이 속한 달의 말일부터 6개월</li>
            </ul>
            <div className="result-meta">법률 자문이 아닌 일정 안내입니다.</div>
          </div>
          <div className="result-card">
            <h4>협의 당사자</h4>
            <ul>
              <li>김은정 · 배우자</li>
              <li>김하준 · 자녀</li>
            </ul>
          </div>
        </div>
        <div className="bubble bubble-user">상속세는 어느 정도입니까.</div>
        <div className="msg-col">
          <div className="agent-label">상속세 시산</div>
          <div className="bubble bubble-assistant">
            가족 정보는 반영되어, 배우자·자녀 질문은 생략합니다. 피상속인께서 사망 당시
            국내 거주자이셨습니까?
          </div>
        </div>
      </div>
      <div className="composer">
        <div className="composer-row">
          <input readOnly value="예, 국내 거주자였습니다." />
          <button type="button" className="send-btn">
            전송
          </button>
        </div>
      </div>
    </div>
  );
}
