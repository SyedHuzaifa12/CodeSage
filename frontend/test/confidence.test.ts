import { describe, expect, it } from "vitest";
import {
  arcDasharray,
  CONFIDENCE_RING_CIRCUMFERENCE,
  CONFIDENCE_TABLE,
  getConfidenceSpec,
} from "@/lib/confidence";

describe("confidence ring mapping", () => {
  it("maps every VerificationStatus and EvidenceConfidence value to a spec", () => {
    for (const key of Object.keys(CONFIDENCE_TABLE)) {
      const spec = getConfidenceSpec(key);
      expect(spec.arcPercent).toBeGreaterThan(0);
      expect(spec.arcPercent).toBeLessThanOrEqual(100);
      expect(spec.colorVar).toMatch(/^--cs-/);
      expect(spec.label.length).toBeGreaterThan(0);
    }
  });

  it("falls back to insufficient_evidence for an unknown value", () => {
    expect(getConfidenceSpec("something_unexpected")).toEqual(CONFIDENCE_TABLE.insufficient_evidence);
  });

  it("gives supported and verified the identical arc percentage (single source of truth)", () => {
    expect(CONFIDENCE_TABLE.supported.arcPercent).toBe(CONFIDENCE_TABLE.verified.arcPercent);
  });

  it("computes a dasharray whose two parts sum to the ring's circumference — no per-instance drift possible", () => {
    for (const pct of [0, 15, 20, 55, 78, 92, 100]) {
      const [dash, gap] = arcDasharray(pct).split(" ").map(Number);
      expect(dash + gap).toBeCloseTo(CONFIDENCE_RING_CIRCUMFERENCE, 1);
    }
  });

  it("reproduces the approved baseline dasharray (~34/3.7 of circumference ~37.7) for the high-confidence state", () => {
    const [dash] = arcDasharray(CONFIDENCE_TABLE.supported.arcPercent).split(" ").map(Number);
    expect(dash).toBeGreaterThan(33);
    expect(dash).toBeLessThan(36);
  });
});
