import { describe, expect, it } from "vitest";

import { hasPendingQuestions } from "../agentData";
import { normalizeChatResponse } from "../api";
import { listScenarios, loadResponse } from "./loadFixture";

/**
 * 실제 백엔드 `/chat` 응답(캡처된 fixture)을 `normalizeChatResponse` 에
 * 통과시키는 계약 테스트.
 *
 * `responses/<name>.json` 이 아직 없는 시나리오는 skip — 응답을 캡처하는
 * 순간(README 참고) 자동으로 켜진다. 재캡처 후 여기가 빨개지면 백엔드가
 * 계약을 바꿨다는 뜻이고, `lib/api.ts` 를 새 모양에 맞춰야 한다.
 */

const scenarios = listScenarios();

describe("계약 fixture — 요청 파일은 전부 존재한다", () => {
  it("requests/ 에 4개 시나리오가 있다", () => {
    expect(scenarios).toEqual([
      "followup",
      "full_pipeline",
      "standard",
      "verification_fail",
    ]);
  });
});

describe.each(scenarios)("계약 fixture — %s", (name) => {
  const response = loadResponse(name);

  it.skipIf(response === null)("normalizeChatResponse 가 봉투를 정규화한다", () => {
    const r = normalizeChatResponse(response);

    expect(r, "정규화 결과가 null — 백엔드 응답 모양이 바뀌었을 수 있음").not.toBeNull();
    expect(r!.contributions.length).toBeGreaterThanOrEqual(1);
    expect(r!.agents.length).toBeGreaterThanOrEqual(1);
    expect(typeof r!.path).toBe("string");
    expect(typeof r!.reply).toBe("string");
    for (const c of r!.contributions) {
      expect(typeof c.agent).toBe("string");
      expect(c.agent.length).toBeGreaterThan(0);
      expect(c.data).toBeTypeOf("object");
    }
  });

  it.skipIf(response === null || name !== "standard")(
    "standard: 단일 에이전트",
    () => {
      const r = normalizeChatResponse(response)!;
      expect(r.contributions).toHaveLength(1);
      expect(r.path).not.toBe("full");
    },
  );

  it.skipIf(response === null || name !== "full_pipeline")(
    "full_pipeline: 멀티 에이전트 카드가 실제로 여러 장",
    () => {
      const r = normalizeChatResponse(response)!;
      expect(r.contributions.length).toBeGreaterThanOrEqual(2);
      expect(r.path).toBe("full");
    },
  );

  it.skipIf(response === null || name !== "verification_fail")(
    "verification_fail: ok=false → needs_review 배지",
    () => {
      const r = normalizeChatResponse(response)!;
      expect(r.verification?.ok).toBe(false);
      expect(r.needs_review).toBe(true);
    },
  );

  it.skipIf(response === null || name !== "followup")(
    "followup: 어떤 contribution 이 되묻기(pending_questions)를 담는다",
    () => {
      const r = normalizeChatResponse(response)!;
      const anyFollowup = r.contributions.some((c) =>
        hasPendingQuestions(c.data ?? {}),
      );
      expect(anyFollowup).toBe(true);
    },
  );
});
