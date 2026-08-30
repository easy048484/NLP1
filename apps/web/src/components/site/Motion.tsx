import { createElement, useEffect, useRef, type ReactNode } from "react";

const prefersReduced = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * 스크롤에 따라 배경 사진이 콘텐츠보다 천천히 따라 내려오는 패럴랙스 이미지.
 * 흑백 처리 포함. reduced-motion이면 고정.
 */
export function ParallaxImage({
  src,
  alt = "",
  speed = 0.12,
  className = "",
  position = "center",
}: {
  src: string;
  alt?: string;
  speed?: number;
  className?: string;
  /** object-position (예: "center 68%") */
  position?: string;
}) {
  const ref = useRef<HTMLImageElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReduced()) return;
    const parent = el.parentElement;
    if (!parent) return;

    let raf = 0;
    const update = () => {
      raf = 0;
      const rect = parent.getBoundingClientRect();
      const vh = window.innerHeight || 1;
      // 요소 중심이 화면 중심에서 얼마나 떨어졌는지 (-1 아래 ~ +1 위)
      const progress = (rect.top + rect.height / 2 - vh / 2) / vh;
      const shift = -progress * speed * 100;
      el.style.transform = `translate3d(0, ${shift.toFixed(1)}px, 0) scale(1.18)`;
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };

    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [speed]);

  return (
    <img
      ref={ref}
      className={`parallax-img bw ${className}`}
      src={src}
      alt={alt}
      aria-hidden={alt ? undefined : true}
      loading="lazy"
      style={{ objectPosition: position }}
    />
  );
}

/**
 * 자식이 뷰포트에 들어오면 부드럽게 떠오르며 나타난다.
 * reduced-motion이면 즉시 표시.
 */
export function Reveal({
  children,
  as = "div",
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  as?: "div" | "section" | "li" | "article";
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (prefersReduced()) {
      el.classList.add("is-visible");
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            el.classList.add("is-visible");
            io.unobserve(el);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return createElement(
    as,
    {
      ref,
      className: `reveal ${className}`.trim(),
      style: delay ? { transitionDelay: `${delay}ms` } : undefined,
    },
    children,
  );
}
