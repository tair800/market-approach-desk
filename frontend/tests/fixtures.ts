import type { ApproachView } from "@/lib/types";

export function approach(overrides: Partial<ApproachView> = {}): ApproachView {
  return {
    id: "00000000-0000-0000-0000-0000000000a1",
    market: {
      id: "00000000-0000-0000-0000-0000000000b1",
      name: "Northgate Speciality",
      underwriter: "R. Okonkwo",
      within_placing_authority: true,
    },
    stage: "initial",
    state: "sent",
    attempt_count: 1,
    blocked_reason: null,
    due_at: "2026-09-01T09:00:00Z",
    follow_up_at: "2026-09-04T09:00:00Z",
    sent_at: "2026-09-01T09:04:00Z",
    follow_up_overdue: false,
    reply_classification: null,
    reply_abstained: false,
    ...overrides,
  };
}
