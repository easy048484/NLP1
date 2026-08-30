import type { ReactNode } from "react";
import { Eyebrow } from "../ui";
import { ParallaxImage } from "./Motion";

/** 안내/서비스/FAQ 상단 히어로 — 흑백 사진 배경(패럴랙스) + 네이비 스크림. */
export function PageHero({
  eyebrow,
  title,
  lead,
  photo = "/photos/kr-family-crossing.jpg",
  photoPosition = "center 62%",
}: {
  eyebrow: string;
  title: string;
  lead?: ReactNode;
  photo?: string;
  photoPosition?: string;
}) {
  return (
    <section className="page-hero page-hero-photo">
      <div className="page-hero-bg-wrap" aria-hidden="true">
        <ParallaxImage src={photo} speed={0.14} position={photoPosition} />
      </div>
      <div className="section-inner page-hero-inner">
        <Eyebrow>{eyebrow}</Eyebrow>
        <h1>{title}</h1>
        {lead && <p className="page-hero-lead">{lead}</p>}
      </div>
    </section>
  );
}
