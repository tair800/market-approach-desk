/**
 * The kill test's published result, and the reading of it.
 *
 * The file is written by `make killtest` to `frontend/public/killtest.json`. It is deliberately not
 * committed: a checked-in result would be a number the console asserts rather than a number a run
 * produced, and ADR-001 says every figure a reader sees comes from a script they can run. Until a
 * run puts the file there, the comparison screen says so.
 *
 * Counts come from the fake carrier receiver, never from the desk's own tables. A system that
 * grades itself from its own records is not measuring anything.
 */

export interface ArmResult {
  /** Approaches the carrier receiver observed for the identity under test. */
  observed: number;
  /** Distinct business identities among them. One, in this harness. */
  distinct_keys: number;
}

export interface KillTestResult {
  /** The business identity under test, as `placement/market/stage`. */
  identity: string;
  n8n: ArmResult;
  python: ArmResult;
  /** ISO instant of the run. */
  ran_at: string;
}

function isArm(value: unknown): value is ArmResult {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const arm = value as Record<string, unknown>;
  return (
    typeof arm.observed === "number" &&
    Number.isFinite(arm.observed) &&
    typeof arm.distinct_keys === "number" &&
    Number.isFinite(arm.distinct_keys)
  );
}

/**
 * Validate before rendering.
 *
 * A half-written or stale-shaped file must produce the "not yet run" state rather than `undefined`
 * in a headline number — a comparison that reports nothing is honest, one that reports `NaN`
 * against a commercial claim is not.
 */
export function parseKillTest(value: unknown): KillTestResult | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.identity !== "string" || typeof candidate.ran_at !== "string") {
    return null;
  }
  if (!isArm(candidate.n8n) || !isArm(candidate.python)) {
    return null;
  }
  return {
    identity: candidate.identity,
    ran_at: candidate.ran_at,
    n8n: { observed: candidate.n8n.observed, distinct_keys: candidate.n8n.distinct_keys },
    python: { observed: candidate.python.observed, distinct_keys: candidate.python.distinct_keys },
  };
}

/** How many approaches beyond the first the receiver saw for one identity. Never negative. */
export function duplicates(arm: ArmResult): number {
  return Math.max(0, arm.observed - arm.distinct_keys);
}

export function armVerdict(arm: ArmResult): { ok: boolean; text: string } {
  const extra = duplicates(arm);
  if (extra > 0) {
    return {
      ok: false,
      text:
        extra === 1
          ? "Market blocked — the receiver saw one duplicate approach."
          : `Market blocked — the receiver saw ${extra} duplicate approaches.`,
    };
  }
  if (arm.observed === 0) {
    return { ok: false, text: "The receiver saw nothing. No approach was delivered." };
  }
  return { ok: true, text: "At most one approach per identity, as claimed." };
}
