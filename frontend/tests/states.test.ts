import { describe, expect, it } from "vitest";

import {
  approachStateBadge,
  formatInstant,
  knownApproachStates,
  replyClassBadge,
  stageLabel,
} from "@/lib/states";

/**
 * The badge vocabulary is the console's only claim about what a state means, so it is the piece
 * worth pinning: a state that silently shares another's colour is a matrix an operator misreads.
 */

const SERVER_STATES = [
  "eligible",
  "claimed",
  "sent",
  "retrying",
  "replied",
  "blocked",
  "dead_lettered",
];

const SERVER_REPLY_CLASSES = [
  "interested",
  "declined",
  "needs_information",
  "referred",
  "unclear",
];

describe("approach state badges", () => {
  it("covers exactly the server's ApproachState vocabulary", () => {
    expect(knownApproachStates().sort()).toEqual([...SERVER_STATES].sort());
  });

  it("gives every state a visually distinct class", () => {
    const classes = SERVER_STATES.map((state) => approachStateBadge(state).className);
    expect(new Set(classes).size).toBe(SERVER_STATES.length);
  });

  it("shows an unrecognised state rather than swallowing it", () => {
    const badge = approachStateBadge("quarantined");
    expect(badge.label).toBe("quarantined");
    expect(badge.className).toContain("badge-unknown");
  });
});

describe("reply classification badges", () => {
  it("covers the closed ReplyClass vocabulary with distinct classes", () => {
    const classes = SERVER_REPLY_CLASSES.map((value) => replyClassBadge(value).className);
    expect(new Set(classes).size).toBe(SERVER_REPLY_CLASSES.length);
  });

  it("labels needs_information readably", () => {
    expect(replyClassBadge("needs_information").label).toBe("needs info");
  });
});

describe("stage labels", () => {
  it("keeps the stage legible without losing which stage it is", () => {
    expect(stageLabel("revised_terms")).toBe("revised terms");
    expect(stageLabel("follow_line")).toBe("follow line");
    expect(stageLabel("initial")).toBe("initial");
  });
});

describe("formatInstant", () => {
  it("renders UTC, so the console and the server read one clock", () => {
    expect(formatInstant("2026-09-04T09:05:00Z")).toBe("2026-09-04 09:05Z");
  });

  it("renders a missing instant as a dash rather than an invalid date", () => {
    expect(formatInstant(null)).toBe("—");
  });

  it("passes through anything it cannot parse", () => {
    expect(formatInstant("not-a-date")).toBe("not-a-date");
  });
});
