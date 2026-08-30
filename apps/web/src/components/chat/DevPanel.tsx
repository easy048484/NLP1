import { useState } from "react";
import type { Turn } from "../../lib/appState";

/** 개발자 모드: 이번 턴의 요청/응답 원본 JSON + 메타. */
export function DevPanel({ debug }: { debug: NonNullable<Turn["debug"]> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="dev-panel">
      <button
        type="button"
        className="dev-panel-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {"</>"} 개발자 정보 · {debug.status ?? "네트워크 오류"} · {debug.latencyMs}ms{" "}
        {open ? "▲" : "▼"}
      </button>
      {open && (
        <div className="dev-panel-body">
          {debug.errorMessage && (
            <div className="dev-panel-row dev-panel-error">오류: {debug.errorMessage}</div>
          )}
          <JsonBlock label="요청 — POST /chat" value={debug.request} />
          <JsonBlock label="응답 원본" value={debug.raw} />
        </div>
      )}
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="dev-json-block">
      <div className="dev-json-label">{label}</div>
      <pre className="dev-json-pre">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}
