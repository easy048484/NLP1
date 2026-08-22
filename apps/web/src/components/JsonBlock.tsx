interface JsonBlockProps {
  label: string;
  value: unknown;
}

/** 개발자 모드에서 요청/응답 JSON을 그대로 보여주는 코드 블록. */
export function JsonBlock({ label, value }: JsonBlockProps) {
  return (
    <div className="dev-json-block">
      <div className="dev-json-label">{label}</div>
      <pre className="dev-json-pre">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}
