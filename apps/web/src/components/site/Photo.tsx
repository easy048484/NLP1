import { ParallaxImage } from "./Motion";

/**
 * 흑백 가족 사진 밴드. 섹션 사이 전폭. 스크롤에 따라 배경이 천천히 따라 내려온다.
 */
export function PhotoBand({
  src,
  alt,
  caption,
  position = "center",
  height = "clamp(220px, 30vw, 380px)",
}: {
  src: string;
  alt: string;
  caption?: string;
  position?: string;
  height?: string;
}) {
  return (
    <section className="photo-band" style={{ height }}>
      <div className="photo-band-bg" aria-hidden="true">
        <ParallaxImage src={src} alt={alt} speed={0.18} position={position} />
      </div>
      <div className="photo-band-scrim" aria-hidden="true" />
      {caption && (
        <div className="photo-band-caption">
          <p>{caption}</p>
        </div>
      )}
    </section>
  );
}
