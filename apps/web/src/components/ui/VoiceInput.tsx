import { useEffect, useRef, useState } from "react";

/**
 * Web Speech API 음성 입력. 미지원/실패 시 조용히 숨겨(=텍스트 입력만 노출)
 * 접근성을 해치지 않는다. 시니어 UX: 말로 설명하는 부담을 낮추는 보조 수단.
 */
interface SpeechRecognitionInstance {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  onresult:
    | ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void)
    | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
}
interface SpeechRecognitionCtor {
  new (): SpeechRecognitionInstance;
}

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function VoiceInput({
  onTranscriptFinal,
  onInterim,
}: {
  onTranscriptFinal: (text: string) => void;
  onInterim?: (text: string) => void;
}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionInstance | null>(null);

  useEffect(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    setSupported(true);
    const rec = new Ctor();
    rec.lang = "ko-KR";
    rec.interimResults = true;
    rec.continuous = false;
    rec.onresult = (e) => {
      let finalText = "";
      let interim = "";
      for (let i = 0; i < e.results.length; i += 1) {
        const t = e.results[i][0].transcript;
        if ((e.results[i] as unknown as { isFinal?: boolean }).isFinal) finalText += t;
        else interim += t;
      }
      if (interim) onInterim?.(interim);
      if (finalText) onTranscriptFinal(finalText.trim());
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    recRef.current = rec;
    return () => rec.stop();
  }, [onTranscriptFinal, onInterim]);

  if (!supported) return null;

  const toggle = () => {
    const rec = recRef.current;
    if (!rec) return;
    if (listening) {
      rec.stop();
      setListening(false);
    } else {
      try {
        rec.start();
        setListening(true);
      } catch {
        setListening(false);
      }
    }
  };

  return (
    <button
      type="button"
      className={`voice-btn${listening ? " listening" : ""}`}
      onClick={toggle}
      aria-pressed={listening}
      aria-label={listening ? "음성 입력 중지" : "음성으로 말하기"}
      title={listening ? "듣는 중… 눌러서 중지" : "음성으로 말하기"}
    >
      🎙<span className="voice-btn-text">{listening ? "듣는 중" : "말하기"}</span>
    </button>
  );
}
