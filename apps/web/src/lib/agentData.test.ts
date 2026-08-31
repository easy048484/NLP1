import { describe, expect, it } from "vitest";
import { parsePendingQuestions } from "./agentData";

/**
 * 오케스트레이터가 여러 에이전트를 한 턴에 실행하면 node_compose() 가
 * output.data 를 dict.update() 로 얕게 합치면서 최상위 평면
 * pending_questions 키를 마지막 에이전트 값으로 덮어쓴다(병합 버그,
 * 백엔드 팀 공유됨). 프론트는 최상위가 아니라 네임스페이스
 * (data[agent].pending_questions) 를 우선 읽어야 각 에이전트의
 * 질문을 정확히 구분해 보여줄 수 있다.
 */
describe("parsePendingQuestions", () => {
  it("여러 에이전트가 동시 응답해도 각자의 네임스페이스 질문을 읽는다", () => {
    const data = {
      // node_compose() 의 dict.update() 로 마지막에 덮어써진, 신뢰할 수 없는 최상위 값
      pending_questions: [
        { question: "상속세 신고 기한을 알고 싶으신가요?", field: "due_date" },
      ],
      decedent_estate: {
        pending_questions: [
          {
            question: "유언장에 도장을 찍으셨나요?",
            field: "seal_answer",
            options: [
              { label: "예", value: "seal_or_fingerprint" },
              { label: "아니오", value: "no_seal" },
            ],
          },
        ],
      },
      heir_navigator: {
        pending_questions: [
          { question: "피상속인의 자녀가 몇 명인가요?", field: "child_count" },
        ],
      },
    };

    const decedentEstateData = { decedent_estate: data.decedent_estate };
    const heirNavigatorData = { heir_navigator: data.heir_navigator };

    const decedentResult = parsePendingQuestions(
      {
        ...data,
        // decedent_estate 카드 렌더링 시엔 contribution.data 가 이렇게 넘어온다고 가정
        ...decedentEstateData,
      },
      "decedent_estate",
    );
    expect(decedentResult?.[0]?.question).toBe("유언장에 도장을 찍으셨나요?");
    expect(decedentResult?.[0]?.field).toBe("seal_answer");

    const heirResult = parsePendingQuestions(
      {
        ...data,
        ...heirNavigatorData,
      },
      "heir_navigator",
    );
    expect(heirResult?.[0]?.question).toBe("피상속인의 자녀가 몇 명인가요?");
  });

  it("네임스페이스에 값이 없으면 최상위 평면 키로 폴백한다", () => {
    const data = {
      pending_questions: [{ question: "폴백 질문", field: "x" }],
      some_other_agent: { note: "no pending_questions here" },
    };
    const result = parsePendingQuestions(data);
    expect(result?.[0]?.question).toBe("폴백 질문");
  });

  it("네임스페이스와 최상위 모두 없으면 null 을 반환한다", () => {
    expect(parsePendingQuestions({ decedent_estate: { body: "x" } })).toBeNull();
  });
});
