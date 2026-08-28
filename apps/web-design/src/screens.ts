export type ScreenId =
  | "login"
  | "signup"
  | "role"
  | "intake"
  | "home"
  | "chat-entry"
  | "chat"
  | "tax"
  | "will";

export const SCREENS: {
  id: ScreenId;
  n: number;
  title: string;
  hint: string;
}[] = [
  { id: "login", n: 1, title: "로그인", hint: "워드마크 · 아이디" },
  { id: "signup", n: 2, title: "회원가입", hint: "성명 · 약관" },
  { id: "role", n: 3, title: "상담 구분", hint: "생전 / 상주" },
  { id: "intake", n: 4, title: "가족관계", hint: "배우자 · 자녀" },
  { id: "home", n: 5, title: "준비 현황", hint: "통장형 준비도" },
  { id: "chat-entry", n: 6, title: "상담 창구", hint: "절차 · 유언 · 세액" },
  { id: "chat", n: 7, title: "상담", hint: "기한 · 당사자 카드" },
  { id: "tax", n: 8, title: "상속세 시산", hint: "단계 입력" },
  { id: "will", n: 9, title: "유언 점검", hint: "충족 · 보완 · 미비" },
];
