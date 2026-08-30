import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../lib/appState";
import { login, register } from "../lib/auth";
import { claimFamilyGraph, getMyFamilyGraph } from "../lib/familyGraph";
import { setIntakeProgress } from "../lib/familyGraphStorage";
import { Button, GoldRule, Wordmark } from "../components/ui";

/**
 * 로그인 / 회원가입. 앱 진입 게이트가 아니라 "이어보기·기기 변경" 시점의
 * 선택지다 (assisted digital — 진입장벽 최소화).
 *
 * 시니어 UX: 입력창·버튼 크게(48px+), 오류는 색만이 아니라 문장으로.
 */
export function AuthScreen({ mode }: { mode: "login" | "signup" }) {
  const navigate = useNavigate();
  const { setAuth, familyGraphId, axis } = useApp();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isSignup = mode === "signup";

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);

    const result = isSignup
      ? await register(email.trim(), password, name.trim())
      : await login(email.trim(), password);

    if (!result.ok || !result.auth) {
      setSubmitting(false);
      setError(result.errorMessage ?? "요청을 처리하지 못했어요.");
      return;
    }

    setAuth(result.auth);

    // 익명으로 만든 그래프를 계정에 연결하고, 이미 저장된 내 그래프가 있으면 인테이크 생략
    if (familyGraphId) await claimFamilyGraph(familyGraphId);
    const mine = await getMyFamilyGraph();
    setSubmitting(false);

    if (mine.ok && mine.data && mine.data.members.length > 0) {
      setIntakeProgress("complete");
      navigate(axis ? "/home" : "/onboarding/role");
    } else {
      navigate(axis ? "/home" : "/onboarding/role");
    }
  };

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-brand">
          <Wordmark size="lg" showTagline />
          <GoldRule />
        </div>

        {!isSignup && (
          <p className="auth-hero">
            생전 준비부터 사후 절차까지,
            <br />
            가족의 다음을 <strong>순서대로</strong> 안내합니다.
          </p>
        )}

        <h1 className="auth-title">{isSignup ? "회원가입" : "로그인"}</h1>
        <p className="auth-lede">
          가족관계·자산 정보처럼 민감한 내용을 다루기 때문에, 상담 기록은 본인
          계정으로만 이어집니다.
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

          <Button type="submit" block disabled={submitting}>
            {submitting ? "잠시만요…" : isSignup ? "가입하고 시작하기" : "로그인"}
          </Button>
        </form>

        <div className="auth-switch">
          {isSignup ? (
            <>
              이미 계정이 있으신가요?{" "}
              <button type="button" onClick={() => navigate("/login")}>
                로그인
              </button>
            </>
          ) : (
            <>
              아직 계정이 없으신가요?{" "}
              <button type="button" onClick={() => navigate("/signup")}>
                회원가입
              </button>
            </>
          )}
        </div>

        <button type="button" className="auth-skip" onClick={() => navigate("/")}>
          홈으로 돌아가기
        </button>
      </div>
    </div>
  );
}
