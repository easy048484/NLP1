/** 상담 축(생전 준비 / 사후 절차) 저장. 온보딩 "상담 구분"에서 정한다. */
import type { ConsultAxis } from "../types";

const AXIS_KEY = "eznext.consult_axis";

export function getAxis(): ConsultAxis | null {
  try {
    const raw = window.localStorage.getItem(AXIS_KEY);
    return raw === "pre_need" || raw === "post_death" ? raw : null;
  } catch {
    return null;
  }
}

export function setAxis(axis: ConsultAxis): void {
  try {
    window.localStorage.setItem(AXIS_KEY, axis);
  } catch {
    /* ignore */
  }
}

export function clearAxis(): void {
  try {
    window.localStorage.removeItem(AXIS_KEY);
  } catch {
    /* ignore */
  }
}

export const AXIS_LABEL: Record<ConsultAxis, string> = {
  pre_need: "생전 준비",
  post_death: "사후 절차",
};
