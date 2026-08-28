import { useState, type FormEvent } from "react";
import { login, register, type StoredAuth } from "../lib/auth";

type Mode = "login" | "signup";

/**
 * 로그인 / 회원가입 화면.
 *
 * 가족관계·자산 정보를 다루는 서비스라 로그인한 사용자만 들어올 수 있고,
 * App.tsx가 토큰이 없을 때 이 화면을 전체 화면으로 띄웁니다. 인증에
 * 성공하면 onAuthed로 토큰+사용자 정보를 넘겨줍니다.
 *
 * 고령 사용자를 고려해 입력창·버튼을 크게 두고, 오류는 색만이 아니라
 * 문장으로 함께 보여줍니다.
 */
export function AuthScreen({ onAuthed }: { onAuthed: (auth: StoredAuth) => void }) {
  const [mode, setMode] = useState<Mode>("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isSignup = mode === "signup";

  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
    setPassword("");
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setError(null);

    const result = isSignup
      ? await register(email.trim(), password, name.trim())
      : await login(email.trim(), password);

    setSubmitting(false);

    if (result.ok && result.auth) {
      onAuthed(result.auth);
    } else {
      setError(result.errorMessage ?? "요청을 처리하지 못했어요.");
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="auth-wordmark">헤리온</span>
          <span className="auth-tagline">제도와 사람, 생전과 사후를 잇다</span>
        </div>

        <h1 className="auth-title">{isSignup ? "회원가입" : "로그인"}</h1>
        <p className="auth-lede">
          가족관계·자산 정보처럼 민감한 내용을 다루기 때문에, 본인만 볼 수
          있도록 계정으로 보호합니다.
        </p>

        <form className="auth-form" onSubmit={handleSubmit}>
          {isSignup && (
            <label className="auth-field">
              <span>성명</span>
              <input
                type="text"
                autoComplete="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={100}
                placeholder="예: 김민준"
              />
            </label>
          )}

          <label className="auth-field">
            <span>이메일</span>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="you@example.com"
            />
          </label>

          <label className="auth-field">
            <span>비밀번호</span>
            <input
              type="password"
              autoComplete={isSignup ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={isSignup ? 8 : undefined}
              placeholder={isSignup ? "8자 이상" : ""}
            />
          </label>

          {error && (
            <div className="auth-error" role="alert">
              ⚠ {error}
            </div>
          )}

          <button type="submit" className="auth-submit" disabled={submitting}>
            {submitting
              ? "잠시만요…"
              : isSignup
                ? "가입하고 시작하기"
                : "로그인"}
          </button>
        </form>

        <div className="auth-switch">
          {isSignup ? (
            <>
              이미 계정이 있으신가요?{" "}
              <button type="button" onClick={() => switchMode("login")}>
                로그인
              </button>
            </>
          ) : (
            <>
              아직 계정이 없으신가요?{" "}
              <button type="button" onClick={() => switchMode("signup")}>
                회원가입
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
