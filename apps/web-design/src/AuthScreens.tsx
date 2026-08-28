import { useState } from "react";
import { Topbar } from "./Topbar";

export function LoginScreen({ onSignup, onNext }: { onSignup: () => void; onNext: () => void }) {
  return (
    <div className="screen">
      <div className="screen-scroll">
        <div className="auth-hero">
          <div className="wordmark">
            <b>가문</b>
            <em>Family Ledger</em>
          </div>
          <div className="gold-rule" />
          <h1>
            남겨질 일과
            <br />
            남겨진 일을
            <br />
            바르게 준비합니다.
          </h1>
          <p>상조·보험 상담처럼, 절차와 세액을 차분히 정리해 드립니다.</p>
        </div>
        <label className="field">
          <span>아이디 (이메일)</span>
          <input type="email" defaultValue="kim@example.com" />
        </label>
        <label className="field">
          <span>비밀번호</span>
          <input type="password" defaultValue="••••••••" />
        </label>
        <button type="button" className="cta" onClick={onNext}>
          로그인
        </button>
        <div className="link-row">
          아직 회원이 아니시면{" "}
          <button type="button" onClick={onSignup}>
            가입 안내
          </button>
        </div>
      </div>
    </div>
  );
}

export function SignupScreen({ onLogin, onNext }: { onLogin: () => void; onNext: () => void }) {
  return (
    <div className="screen">
      <Topbar title="회원가입" subtitle="상담 기록은 회원 계정으로만 이어집니다." />
      <div className="screen-scroll">
        <label className="field">
          <span>성명</span>
          <input defaultValue="김민준" />
        </label>
        <label className="field">
          <span>이메일</span>
          <input type="email" defaultValue="kim@example.com" />
        </label>
        <label className="field">
          <span>비밀번호</span>
          <input type="password" defaultValue="••••••••" />
        </label>
        <label className="field">
          <span>비밀번호 확인</span>
          <input type="password" defaultValue="••••••••" />
        </label>
        <button type="button" className="cta" onClick={onNext}>
          약관 동의 후 가입
        </button>
        <div className="link-row">
          이미 회원이시면{" "}
          <button type="button" onClick={onLogin}>
            로그인
          </button>
        </div>
      </div>
    </div>
  );
}

export function RoleScreen({ onNext }: { onNext: () => void }) {
  const [role, setRole] = useState<"heir" | "decedent">("heir");
  return (
    <div className="screen">
      <Topbar title="상담 구분" subtitle="입장에 따라 준비 항목이 달라집니다." />
      <div className="screen-scroll">
        <div className="role-grid">
          <button
            type="button"
            className={`role-card${role === "decedent" ? " role-card-on" : ""}`}
            onClick={() => setRole("decedent")}
          >
            <div className="role-kicker">생전</div>
            <h3>피상속인</h3>
            <p>유언의 형식과 남길 재산을 미리 정리하고자 합니다. 가족에게 남길 준비를 돕습니다.</p>
          </button>
          <button
            type="button"
            className={`role-card${role === "heir" ? " role-card-on" : ""}`}
            onClick={() => setRole("heir")}
          >
            <div className="role-kicker">상주 · 상속</div>
            <h3>상속인</h3>
            <p>돌아가신 뒤의 신고, 기한, 협의와 상속세를 순서대로 챙기고자 합니다.</p>
          </button>
        </div>
        <button type="button" className="cta" onClick={onNext}>
          {role === "heir" ? "상속인으로 진행" : "피상속인으로 진행"}
        </button>
      </div>
    </div>
  );
}
