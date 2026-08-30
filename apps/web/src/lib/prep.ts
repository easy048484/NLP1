import type { AgentPlan, ConsultAxis, FamilyGraphOut, FinancialProfile } from "../types";
import type { StatusKind } from "../components/ui";
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
  financialProfile,
}: {
  axis: ConsultAxis | null;
  familyGraph: FamilyGraphOut | null;
  plan: AgentPlan | null;
  planChecks: Record<string, boolean>;
  financialProfile: FinancialProfile | null;
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

  const doneSteps = plan ? plan.steps.filter((s) => planChecks[s.id] ?? s.done).length : 0;
  const totalSteps = plan?.steps.length ?? 0;
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

  const taxStatus: StatusKind = financialProfile ? "wip" : "todo";
  const taxDesc = financialProfile ? "재산 정보 입력됨" : "재산가액 미입력";

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
    const assetStatus: StatusKind = financialProfile ? "done" : "todo";
    items.push({
      key: "asset",
      title: "자산 정리",
      desc: financialProfile
        ? `자산 ${financialProfile.assets.length}건 · 은퇴갭 추정됨`
        : "예금·보험·부동산·연금 정리 전",
      status: assetStatus,
      statusLabel: STATUS_LABEL[assetStatus],
      route: "/chat",
    });
    items.push({
      key: "will",
      title: "유언 요건",
      desc: "자필증서 형식 요건 점검 전",
      status: "todo",
      statusLabel: STATUS_LABEL.todo,
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
      desc: "유언장이 있다면 형식 요건 점검",
      status: "todo",
      statusLabel: STATUS_LABEL.todo,
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
