import { describe, expect, it } from "vitest";

import { normalizeChatResponse } from "./api";

/**
 * `normalizeChatResponse` 계약 회귀 테스트.
 *
 * 이 프로젝트에서 프론트 파서가 깨진 패턴은 늘 "백엔드가 필드 모양을 바꿨는데
 * 타입에러도 빌드에러도 안 나고 조용히 undefined" 였다(`Record<string, unknown>`
 * 라서). 여기서는 백엔드가 실제로 주는 세 가지 봉투 모양을 인라인 mock 으로
 * 재현해서, 정규화 결과의 핵심 필드가 어긋나면 즉시 빨개지게 한다.
 *
 * 실제 백엔드 응답을 캡처한 fixture 기반 테스트는 __fixtures__/ 로 별도. 이
 * 파일은 fixture·백엔드 없이 도는 순수 유닛 테스트다.
 */

/** "현재 백엔드" 모양: AgentOutput(flat) + {agents, path, verification, data(평면 병합)} */
function currentBackendResponse(
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    agent: "tax_calculator",
    reply: "예상 상속세는 1,234,000원입니다.",
    agents: ["tax_calculator"],
    path: "standard",
    data: { tax_calculator: { last_result: { final_amount: 1_234_000 } } },
    ...over,
  };
}

describe("normalizeChatResponse — 방어적 입력", () => {
  it("null / 원시값 / 배열은 null 을 반환한다", () => {
    expect(normalizeChatResponse(null)).toBeNull();
    expect(normalizeChatResponse("x")).toBeNull();
    expect(normalizeChatResponse(42)).toBeNull();
  });

  it("agent 도 agents 도 contributions 도 없으면 null", () => {
    expect(normalizeChatResponse({ reply: "안녕하세요" })).toBeNull();
  });
});

describe("normalizeChatResponse — 현재 백엔드 (agents[] + 평면 data)", () => {
  it("단일 에이전트 → contribution 1개, reply/path/primary_agent 매핑", () => {
    const r = normalizeChatResponse(currentBackendResponse());
    expect(r).not.toBeNull();
    expect(r?.reply).toBe("예상 상속세는 1,234,000원입니다.");
    expect(r?.path).toBe("standard");
    expect(r?.agents).toEqual(["tax_calculator"]);
    expect(r?.contributions).toHaveLength(1);
    expect(r?.contributions[0].agent).toBe("tax_calculator");
    expect(r?.primary_agent).toBe("tax_calculator");
  });

  it("멀티 에이전트(full pipeline) → agents 순서대로 contribution 이 그만큼 생긴다", () => {
    const r = normalizeChatResponse(
      currentBackendResponse({
        agents: ["asset_organizer", "tax_calculator"],
        path: "full",
        data: {
          asset_organizer: { estate: { net: 5 } },
          tax_calculator: { last_result: { final_amount: 1_234_000 } },
        },
      }),
    );
    expect(r?.path).toBe("full");
    expect(r?.contributions.map((c) => c.agent)).toEqual([
      "asset_organizer",
      "tax_calculator",
    ]);
    // 대표 에이전트는 DAG 의 마지막
    expect(r?.primary_agent).toBe("tax_calculator");
  });

  it("각 contribution.data 는 자기 네임스페이스 슬라이스(rawData[agent])만 담는다", () => {
    const r = normalizeChatResponse(
      currentBackendResponse({
        agents: ["asset_organizer", "tax_calculator"],
        data: {
          asset_organizer: { mine: "AO" },
          tax_calculator: { mine: "TAX" },
        },
      }),
    );
    const [ao, tax] = r!.contributions;
    expect(ao.data).toEqual({ mine: "AO" });
    expect(tax.data).toEqual({ mine: "TAX" });
    // 서로의 데이터가 섞이지 않는다
    expect(ao.data.mine).not.toBe("TAX");
  });

  it("agents 에 중복이 있어도 contribution 은 한 번만 만든다", () => {
    const r = normalizeChatResponse(
      currentBackendResponse({ agents: ["tax_calculator", "tax_calculator"] }),
    );
    expect(r?.contributions).toHaveLength(1);
  });

  it("path 가 없으면 'standard' 로 기본값", () => {
    const res = currentBackendResponse();
    delete res.path;
    expect(normalizeChatResponse(res)?.path).toBe("standard");
  });
});

describe("normalizeChatResponse — contributions[] 계약", () => {
  it("백엔드가 contributions 를 주면 그대로 쓰고 평면 data 는 무시한다", () => {
    const r = normalizeChatResponse(
      currentBackendResponse({
        agents: ["decedent_estate", "heir_navigator"],
        data: { pending_questions: [{ question: "평면 병합 잔재", field: "x" }] },
        contributions: [
          {
            agent: "decedent_estate",
            reply: "유언장 검토 결과",
            data: { pending_questions: [{ question: "유언장 질문", field: "a" }] },
          },
          {
            agent: "heir_navigator",
            reply: "절차 안내",
            data: { pending_questions: [{ question: "절차 질문", field: "b" }] },
          },
        ],
      }),
    );
    const [de, hn] = r!.contributions;
    // 겹치는 키(pending_questions)가 소유자별로 보존된다 — 평면 병합 덮어쓰기 해소
    expect(de.data.pending_questions).toEqual([
      { question: "유언장 질문", field: "a" },
    ]);
    expect(hn.data.pending_questions).toEqual([
      { question: "절차 질문", field: "b" },
    ]);
  });

  it("contributions 가 없는 구버전 응답은 네임스페이스 슬라이스만으로 쪼갠다(평면 키는 안 끌어옴)", () => {
    const r = normalizeChatResponse(
      currentBackendResponse({
        agents: ["decedent_estate"],
        data: {
          will_type: "평면-잔재",
          decedent_estate: { will_type: "namespace-값" },
        },
      }),
    );
    const c = r!.contributions[0];
    expect(c.data.will_type).toBe("namespace-값");
    // LEGACY_FLAT_KEYS 제거: 네임스페이스 밖 평면 키는 더 이상 슬라이스에 섞지 않는다
    const r2 = normalizeChatResponse(
      currentBackendResponse({
        agents: ["decedent_estate"],
        data: { will_type: "평면-값", decedent_estate: {} },
      }),
    );
    expect(r2!.contributions[0].data.will_type).toBeUndefined();
  });
});

describe("normalizeChatResponse — verification / needs_review", () => {
  it("verification.ok === false → needs_review true + verification 파싱", () => {
    const r = normalizeChatResponse(
      currentBackendResponse({
        verification: {
          ok: false,
          mode: "concat_after_failure",
          mismatches: ["1240000원"],
        },
      }),
    );
    expect(r?.needs_review).toBe(true);
    expect(r?.verification).toEqual({
      ok: false,
      mode: "concat_after_failure",
      mismatches: ["1240000원"],
    });
  });

  it("verification.ok === true → needs_review false", () => {
    const r = normalizeChatResponse(
      currentBackendResponse({
        verification: { ok: true, mode: "concat", mismatches: [] },
      }),
    );
    expect(r?.needs_review).toBe(false);
    expect(r?.verification?.ok).toBe(true);
  });

  it("verification 이 아예 없으면 null, needs_review 는 명시 플래그를 따른다", () => {
    const r = normalizeChatResponse(currentBackendResponse({ needs_review: true }));
    expect(r?.verification).toBeNull();
    expect(r?.needs_review).toBe(true);
  });

  it("mismatches 가 배열이 아니면 빈 배열로 정규화", () => {
    const r = normalizeChatResponse(
      currentBackendResponse({
        verification: { ok: false, mode: "x", mismatches: "깨진 값" },
      }),
    );
    expect(r?.verification?.mismatches).toEqual([]);
  });
});

describe("normalizeChatResponse — estate / will_status 평면 필드", () => {
  it("financial_profile(flat) → estate 요약 (자산합 - 부채 = 순자산)", () => {
    const r = normalizeChatResponse(
      currentBackendResponse({
        financial_profile: {
          real_estate_value: 500_000_000,
          financial_assets: 300_000_000,
          total_debts: 100_000_000,
        },
      }),
    );
    expect(r?.estate).toEqual({
      totalAssets: 800_000_000,
      totalDebts: 100_000_000,
      net: 700_000_000,
    });
  });

  it("financial_profile 값이 하나도 없으면 estate 는 null", () => {
    expect(normalizeChatResponse(currentBackendResponse())?.estate).toBeNull();
  });

  it("will_status.checked 가 boolean 이면 파싱, 없으면 null", () => {
    const withWill = normalizeChatResponse(
      currentBackendResponse({
        will_status: { checked: true, no_will: false, overall_grade: "yellow" },
      }),
    );
    expect(withWill?.will_status).toMatchObject({
      checked: true,
      no_will: false,
      overall_grade: "yellow",
    });
    expect(normalizeChatResponse(currentBackendResponse())?.will_status).toBeNull();
  });
});

describe("normalizeChatResponse — 다른 계약 세대", () => {
  it("최종 계약(contributions[]) 은 그대로 통과시키고 agents 를 유도한다", () => {
    const r = normalizeChatResponse({
      reply: "합성 답변",
      contributions: [
        { agent: "decedent_estate", reply: "유언장 없음", data: {} },
        { agent: "tax_calculator", reply: "세액 계산", data: {} },
      ],
      path: "full",
      verification: { ok: true, mode: "synthesized", mismatches: [] },
    });
    expect(r?.contributions).toHaveLength(2);
    expect(r?.agents).toEqual(["decedent_estate", "tax_calculator"]);
    expect(r?.primary_agent).toBe("decedent_estate");
  });

  it("아주 옛 단일 AgentOutput(agents 없음) → 1-contribution 으로 감싼다", () => {
    const r = normalizeChatResponse({
      agent: "heir_navigator",
      reply: "안심상속 원스톱 안내",
      data: { plan: { timeline: [{ step: "1", title: "사망신고" }] } },
    });
    expect(r?.contributions).toHaveLength(1);
    expect(r?.contributions[0].agent).toBe("heir_navigator");
    expect(r?.agents).toEqual(["heir_navigator"]);
    expect(r?.plan?.steps[0].title).toBe("사망신고");
  });
});
