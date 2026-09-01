/**
 * 로컬 백엔드 run()에 가상 가족·금액을 넣어 확인한 last_result 계약 예시.
 * 실제 사용자/DB 데이터가 아니며 세법의 정확성을 검증하는 골든 테스트가 아니다.
 * 테스트마다 새 객체를 반환해 값 변경이 다른 테스트에 섞이지 않게 한다.
 */
export function taxFixture() {
  return {
    status: "calculated",
    last_result: {
      total_inherited_property: 1_500_000_000,
      deductible_expenses: 5_000_000,
      taxable_inheritance_value: 1_495_000_000,
      total_inheritance_deduction: 1_000_000_000,
      inheritance_tax_base: 495_000_000,
      calculated_inheritance_tax: 89_000_000,
      filing_tax_credit: 2_670_000,
      estimated_tax_due: 86_330_000,
      estimated_filing_deadline: null as string | null,
      warnings: [
        "이 결과는 입력한 금액을 기준으로 계산한 참고용 시뮬레이션입니다.",
        "상속개시일이 없어 신고기한을 계산하지 않았습니다.",
      ],
    },
  };
}

export function shareFixture() {
  return {
    status: "possible_gap",
    asked_slot: null,
    missing_fields: [],
    last_result: {
      status: "possible_gap",
      basis_amount: 700_000_000,
      heirs: [
        {
          name: "배우자", relation: "spouse",
          statutory_share_fraction: "3/7", statutory_share_amount: 300_000_000,
          forced_share_rate_fraction: "1/2", basic_forced_share_estimate: 150_000_000,
          planned_acquisition: 0 as number | null, simple_gap: 150_000_000 as number | null,
        },
        {
          name: "자녀 A", relation: "child",
          statutory_share_fraction: "2/7", statutory_share_amount: 200_000_000,
          forced_share_rate_fraction: "1/2", basic_forced_share_estimate: 100_000_000,
          planned_acquisition: 700_000_000 as number | null, simple_gap: 0 as number | null,
        },
        {
          name: "자녀 B", relation: "child",
          statutory_share_fraction: "2/7", statutory_share_amount: 200_000_000,
          forced_share_rate_fraction: "1/2", basic_forced_share_estimate: 100_000_000,
          planned_acquisition: 0 as number | null, simple_gap: 100_000_000 as number | null,
        },
      ],
      warnings: [
        "생전 점검 결과는 현재 가족관계와 재산을 기준으로 한 예상치입니다.",
        "일부 상속인에게 기본 유류분보다 적게 배분될 가능성이 있습니다.",
      ],
    },
  };
}
