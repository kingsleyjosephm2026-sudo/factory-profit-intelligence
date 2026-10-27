import { describe, expect, it } from "vitest";
import { fmtMoney, fmtPct, fmtValue, tone } from "./format";

describe("format", () => {
  it("shows n/a instead of 0 for missing values", () => {
    expect(fmtPct(null)).toBe("n/a");
    expect(fmtMoney(undefined)).toBe("n/a");
    expect(fmtValue(null, "%", "INR")).toBe("n/a");
  });
  it("formats INR in lakh/crore", () => {
    expect(fmtMoney(7806445, "INR", true)).toBe("₹78.06 L");
    expect(fmtMoney(25000000, "INR", true)).toBe("₹2.50 Cr");
  });
  it("judges direction against what is good for the metric", () => {
    expect(tone(5, "lower")).toBe("bad");
    expect(tone(-5, "lower")).toBe("good");
    expect(tone(5, "higher")).toBe("good");
    expect(tone(0, "higher")).toBe("flat");
    expect(tone(null, "higher")).toBe("flat");
  });
});
