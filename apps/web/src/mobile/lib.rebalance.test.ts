import { describe, expect, it } from "vitest";
import { rebalancePercents } from "./lib";

describe("rebalancePercents", () => {
  const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);

  it("keeps total at 100 and splits the rest by previous ratio", () => {
    const out = rebalancePercents({ 배우자: 43, 자녀1: 29, 자녀2: 28 }, "배우자", 60);
    expect(out.배우자).toBe(60);
    expect(sum(out)).toBe(100);
    expect(out.자녀1).toBeGreaterThanOrEqual(out.자녀2);
  });

  it("splits evenly when others were all zero", () => {
    const out = rebalancePercents({ 배우자: 100, 자녀1: 0, 자녀2: 0 }, "배우자", 40);
    expect(out).toEqual({ 배우자: 40, 자녀1: 30, 자녀2: 30 });
  });

  it("handles extremes", () => {
    expect(sum(rebalancePercents({ a: 33, b: 33, c: 34 }, "b", 100))).toBe(100);
    expect(rebalancePercents({ a: 50, b: 50 }, "a", 0)).toEqual({ a: 0, b: 100 });
    expect(rebalancePercents({ a: 100 }, "a", 30)).toEqual({ a: 100 });
  });
});
