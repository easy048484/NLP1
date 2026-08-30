import { useState } from "react";
import { useApp } from "../../lib/appState";
import { VoiceInput } from "../ui";

/**
 * 보조 입력. 주 사용 흐름은 상단 기능 타일 + 답변 속 선택 버튼이고,
 * 이건 "그 외 궁금한 점"을 직접 물어보는 용도.
 */
export function Composer() {
  const { send, loading } = useApp();
  const [value, setValue] = useState("");

  const submit = (text: string) => {
    const t = text.trim();
    if (!t || loading) return;
    setValue("");
    void send(t);
  };

  return (
    <div className="composer">
      <div className="composer-row">
        <input
          className="composer-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) submit(value);
          }}
          placeholder="그 외 궁금한 점을 직접 물어보셔도 됩니다"
          aria-label="직접 질문 입력"
          disabled={loading}
        />
        <VoiceInput
          onTranscriptFinal={(text) => setValue((prev) => (prev ? `${prev} ${text}` : text))}
        />
        <button
          type="button"
          className="btn btn-primary composer-send"
          onClick={() => submit(value)}
          disabled={loading || !value.trim()}
        >
          보내기
        </button>
      </div>
    </div>
  );
}
