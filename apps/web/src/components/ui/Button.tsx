import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "outline" | "ghost" | "gold";

/** 공통 버튼. 최소 높이 48px는 ui.css에서 보장. */
export function Button({
  variant = "primary",
  block = false,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; block?: boolean }) {
  return (
    <button
      type="button"
      className={`btn btn-${variant}${block ? " btn-block" : ""} ${className}`}
      {...rest}
    />
  );
}
