import { useRef, useState } from "react";
import { useApp } from "../../lib/appState";
import { Button, Dialog, VoiceInput } from "../ui";

/**
 * 보조 입력. 주 사용 흐름은 상단 기능 타일 + 답변 속 선택 버튼이고,
 * 이건 "그 외 궁금한 점"을 직접 물어보거나 사진(유언장·안심상속 조회결과)을
 * 올리는 용도.
 */
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export function Composer() {
  const { send, loading } = useApp();
  const [value, setValue] = useState("");
  const [image, setImage] = useState<{ base64: string; mediaType: string; name: string } | null>(
    null,
  );
  const [imgError, setImgError] = useState<string | null>(null);
  const [showUploadNotice, setShowUploadNotice] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const pickImage = (file: File) => {
    setImgError(null);
    if (!file.type.startsWith("image/")) {
      setImgError("이미지 파일만 올릴 수 있어요.");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setImgError("5MB 이하 이미지만 올릴 수 있어요.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result);
      const base64 = result.includes(",") ? result.slice(result.indexOf(",") + 1) : result;
      setImage({ base64, mediaType: file.type, name: file.name });
    };
    reader.onerror = () => setImgError("사진을 읽지 못했어요. 다시 시도해 주세요.");
    reader.readAsDataURL(file);
  };

  const submit = () => {
    const t = value.trim();
    if ((!t && !image) || loading) return;
    setValue("");
    const img = image;
    setImage(null);
    void send(t, img ? { image: { base64: img.base64, mediaType: img.mediaType } } : undefined);
  };

  return (
    <div className="composer">
      {image && (
        <div className="composer-attachment">
          <span className="composer-attachment-name">🖼️ {image.name}</span>
          <button
            type="button"
            className="composer-attachment-x"
            onClick={() => setImage(null)}
            aria-label="사진 제거"
          >
            ✕
          </button>
        </div>
      )}
      {imgError && <p className="composer-img-error">{imgError}</p>}

      <div className="composer-row">
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) pickImage(f);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          className="composer-attach"
          onClick={() => setShowUploadNotice(true)}
          disabled={loading}
          aria-label="사진 첨부 (유언장·안심상속 조회결과)"
          title="유언장·안심상속 조회결과 사진 올리기"
        >
          📷
        </button>
        <input
          className="composer-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) submit();
          }}
          placeholder={image ? "사진에 대해 덧붙일 말 (선택)" : "그 외 궁금한 점을 직접 물어보셔도 됩니다"}
          aria-label="직접 질문 입력"
          disabled={loading}
        />
        <VoiceInput
          onTranscriptFinal={(text) => setValue((prev) => (prev ? `${prev} ${text}` : text))}
        />
        <button
          type="button"
          className="btn btn-primary composer-send"
          onClick={submit}
          disabled={loading || (!value.trim() && !image)}
        >
          보내기
        </button>
      </div>

      {showUploadNotice && (
        <Dialog
          title="업로드 전 확인해 주세요"
          onClose={() => setShowUploadNotice(false)}
          footer={
            <>
              <Button variant="outline" onClick={() => setShowUploadNotice(false)}>
                취소
              </Button>
              <Button
                onClick={() => {
                  setShowUploadNotice(false);
                  fileRef.current?.click();
                }}
              >
                확인
              </Button>
            </>
          }
        >
          <div className="upload-notice">
            <p className="upload-notice-intro">
              <span aria-hidden="true">🔒</span>
              유언장 사진이나 안심상속 원스톱 조회결과 캡처는 내용 판독을 위해
              외부 AI 서비스로 전송됩니다. 사진은 판독 후 저장하지 않습니다.
            </p>

            <div className="upload-notice-rule upload-notice-warn">
              <span className="upload-notice-icon" aria-hidden="true">
                ⚠
              </span>
              <div>
                <strong>가려주세요!</strong>
                <p>주민등록번호 · 전화번호 · 계좌번호 전체 자릿수</p>
              </div>
            </div>

            <div className="upload-notice-rule upload-notice-keep">
              <span className="upload-notice-icon" aria-hidden="true">
                ✓
              </span>
              <div>
                <strong>가리지 말아주세요</strong>
                <p>
                  <span className="upload-notice-tag">유언장</span>
                  성명 · 주소 · 작성 날짜
                </p>
                <p>
                  <span className="upload-notice-tag">안심상속</span>
                  자산·부채 종류와 금액, 기관명
                </p>
              </div>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
