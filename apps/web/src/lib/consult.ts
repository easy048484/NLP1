/**
 * 상담 축(생전 준비 / 사후 절차) 저장. 온보딩 "상담 구분"에서 정한다.
 *
 * 저장 위치는 로그인 여부에 따라 갈린다 — scopedStorage 참고.
 */
import type { ConsultAxis } from "../types";
import { clearScoped, readScoped, writeScoped } from "./scopedStorage";

const AXIS_KEY = "eznext.consult_axis";

export function getAxis(): ConsultAxis | null {
  const raw = readScoped(AXIS_KEY);
  return raw === "pre_need" || raw === "post_death" ? raw : null;
}

export function setAxis(axis: ConsultAxis): void {
  writeScoped(AXIS_KEY, axis);
}

export function clearAxis(): void {
  clearScoped(AXIS_KEY);
}

export const AXIS_LABEL: Record<ConsultAxis, string> = {
  pre_need: "생전 준비",
  post_death: "사후 절차",
};
