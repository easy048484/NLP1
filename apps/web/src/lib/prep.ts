import type {
  AgentPlan,
  ConsultAxis,
  EstateSummary,
  FamilyGraphOut,
  WillStatus,
} from "../types";
import type { StatusKind } from "../components/ui";
import { formatWon } from "./format";
import { RELATION_LABELS } from "./relations";

export interface PrepItem {
  key: "family" | "procedure" | "tax" | "will" | "asset";
  title: string;
  desc: string;
  status: StatusKind;
  statusLabel: string;
  route: string;
}

const STATUS_LABEL: Record<StatusKind, string> = {
  done: "등록",
  wip: "진행",
  todo: "대기",
  attention: "보완",
};

/** 현재 상태로 준비 현황 4~5개 항목을 만든다. 사후/생전 축에 따라 구성이 다르다. */
export function buildPrep({
  axis,
  familyGraph,
  plan,
  planChecks,
  estate,
  willStatus,
}: {
  axis: ConsultAxis | null;
  familyGraph: FamilyGraphOut | null;
  plan: AgentPlan | null;
  planChecks: Record<string, boolean>;
  estate: EstateSummary | null;
  willStatus: WillStatus | null;
}): PrepItem[] {
  const memberCount = familyGraph?.members.length ?? 0;
  const familyDesc =
    memberCount > 0
      ? familyGraph!.members
          .slice(0, 3)
          .map((m) => `${RELATION_LABELS[m.relation]} ${m.name}`)
          .join(" · ")
      : "아직 등록 전";
  const familyStatus: StatusKind = memberCount > 0 ? "done" : "todo";

  const steps = plan?.steps ?? [];
  const doneSteps = steps.filter((s) => planChecks[s.id] ?? s.done).length;
  const totalSteps = steps.length;
  const procedureStatus: StatusKind = !plan
    ? "todo"
    : doneSteps === 0
      ? "wip"
      : doneSteps === totalSteps
        ? "done"
        : "wip";
  const procedureDesc = plan
    ? `${totalSteps}건 중 ${doneSteps}건 완료`
    : "상담을 시작하면 일정이 만들어져요";

  const taxStatus: StatusKind = estate ? "wip" : "todo";
  const taxDesc = estate
    ? `순자산 ${formatWon(estate.net)} (자산 ${formatWon(estate.totalAssets)} · 부채 ${formatWon(estate.totalDebts)})`
    : "재산가액 미입력";

  // 유언 요건 상태 — decedent_estate 판정(willStatus)이 있으면 반영.
  let willStatusKind: StatusKind = "todo";
  let willDesc =
    axis === "pre_need"
      ? "자필증서 형식 요건 점검 전"
      : "유언장이 있다면 형식 요건 점검";
  if (willStatus?.no_will) {
    willStatusKind = "done";
    willDesc = "유언장 없음 — 법정상속분 기준으로 진행";
  } else if (willStatus?.has_effect === true) {
    willStatusKind = "done";
    willDesc = "유효한 유언장으로 확인됨";
  } else if (willStatus?.overall_grade === "red") {
    willStatusKind = "attention";
    willDesc = "형식 요건 미비 — 보완이 필요합니다";
  } else if (willStatus?.overall_grade === "yellow") {
    willStatusKind = "attention";
    willDesc = "쟁점이 있어 확인이 필요합니다";
  } else if (willStatus?.checked) {
    willStatusKind = "wip";
    willDesc = "유언장 요건 점검 중";
  }

  const items: PrepItem[] = [
    {
      key: "family",
      title: "가족관계",
      desc: familyDesc,
      status: familyStatus,
      statusLabel: STATUS_LABEL[familyStatus],
      route: "/onboarding/family",
    },
  ];

  if (axis === "pre_need") {
    const assetStatus: StatusKind = estate ? "done" : "todo";
    items.push({
      key: "asset",
      title: "자산 정리",
      desc: estate
        ? `순자산 ${formatWon(estate.net)}`
        : "예금·보험·부동산·연금 정리 전",
      status: assetStatus,
      statusLabel: STATUS_LABEL[assetStatus],
      route: "/chat",
    });
    items.push({
      key: "will",
      title: "유언 요건",
      desc: willDesc,
      status: willStatusKind,
      statusLabel: STATUS_LABEL[willStatusKind],
      route: "/chat",
    });
    items.push({
      key: "tax",
      title: "예상 상속세",
      desc: taxDesc,
      status: taxStatus,
      statusLabel: STATUS_LABEL[taxStatus],
      route: "/chat",
    });
  } else {
    items.push({
      key: "procedure",
      title: "상속 절차",
      desc: procedureDesc,
      status: procedureStatus,
      statusLabel: STATUS_LABEL[procedureStatus],
      route: "/chat",
    });
    items.push({
      key: "tax",
      title: "예상 상속세",
      desc: taxDesc,
      status: taxStatus,
      statusLabel: STATUS_LABEL[taxStatus],
      route: "/chat",
    });
    items.push({
      key: "will",
      title: "유언 요건",
      desc: willDesc,
      status: willStatusKind,
      statusLabel: STATUS_LABEL[willStatusKind],
      route: "/chat",
    });
  }

  return items;
}

export function prepPercent(items: PrepItem[]): number {
  if (items.length === 0) return 0;
  const score = items.reduce((sum, it) => {
    if (it.status === "done") return sum + 1;
    if (it.status === "wip" || it.status === "attention") return sum + 0.5;
    return sum;
  }, 0);
  return Math.round((score / items.length) * 100);
}
