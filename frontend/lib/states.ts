/**
 * How the seven approach states and the five reply classes are shown.
 *
 * The vocabularies are closed on the server — `ApproachState` in `domain/identity.py` and
 * `ReplyClass` in `replies/schema.py` — and this file is the only place the console decides what
 * either looks like. One lookup, so a badge cannot mean one thing on the board and another in a
 * table cell.
 *
 * Unknown values are shown, not swallowed. An operator who sees a state this build does not know
 * about should see its name rather than an empty cell.
 */

export interface BadgeSpec {
  /** The label rendered in the badge. */
  label: string;
  /** A static class from `globals.css`. Static because Tailwind cannot see a constructed name. */
  className: string;
  /** One line an operator can hover for. */
  title: string;
}

const UNKNOWN_STATE_CLASS = "badge badge-unknown";

const APPROACH_STATES: Record<string, BadgeSpec> = {
  eligible: {
    label: "eligible",
    className: "badge badge-eligible",
    title: "Eligible for approach. Nothing is reserved and no email exists.",
  },
  claimed: {
    label: "claimed",
    className: "badge badge-claimed",
    title: "Reserved by a scheduler inside the claim transaction. No email exists yet.",
  },
  sent: {
    label: "sent",
    className: "badge badge-sent",
    title: "The carrier receiver accepted the approach. Irreversible.",
  },
  retrying: {
    label: "retrying",
    className: "badge badge-retrying",
    title: "The send failed in a way that is safe to retry, and is scheduled to be.",
  },
  replied: {
    label: "replied",
    className: "badge badge-replied",
    title: "An underwriter answered. The classification sits on the reply.",
  },
  blocked: {
    label: "blocked",
    className: "badge badge-blocked",
    title: "Refused before any send, by a conflict rule evaluated inside the claim.",
  },
  dead_lettered: {
    label: "dead-lettered",
    className: "badge badge-dead",
    title: "Retries are exhausted. A person looks at it; nothing automatic will.",
  },
};

/** States from which no further send may be made. Mirrors `TERMINAL_STATES` on the server. */
export const TERMINAL_STATES: ReadonlySet<string> = new Set([
  "sent",
  "replied",
  "blocked",
  "dead_lettered",
]);

export function approachStateBadge(state: string): BadgeSpec {
  return (
    APPROACH_STATES[state] ?? {
      label: state || "unknown",
      className: UNKNOWN_STATE_CLASS,
      title: "A state this build of the console does not recognise.",
    }
  );
}

export function knownApproachStates(): string[] {
  return Object.keys(APPROACH_STATES);
}

const REPLY_CLASSES: Record<string, BadgeSpec> = {
  interested: {
    label: "interested",
    className: "badge badge-interested",
    title: "The underwriter will quote, or has quoted.",
  },
  declined: {
    label: "declined",
    className: "badge badge-declined",
    title: "The underwriter will not quote. Starts the cooling period.",
  },
  needs_information: {
    label: "needs info",
    className: "badge badge-needsinfo",
    title: "They need something before they can answer.",
  },
  referred: {
    label: "referred",
    className: "badge badge-referred",
    title: "Passed to a colleague, another office, or a different underwriting team.",
  },
  unclear: {
    label: "unclear",
    className: "badge badge-unclear",
    title: "Out of office, an acknowledgement, or anything that is not an answer.",
  },
};

export function replyClassBadge(classification: string): BadgeSpec {
  return (
    REPLY_CLASSES[classification] ?? {
      label: classification || "unknown",
      className: UNKNOWN_STATE_CLASS,
      title: "A classification this build of the console does not recognise.",
    }
  );
}

const STAGE_LABELS: Record<string, string> = {
  initial: "initial",
  revised_terms: "revised terms",
  follow_line: "follow line",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

/**
 * One fixed rendering for every instant on screen.
 *
 * UTC, because a desk that spans offices reads one clock, and because the server decided
 * `follow_up_overdue` against UTC. Rendering a local time next to a server-decided flag invites an
 * operator to conclude the flag is wrong when it is only in a different zone.
 */
export function formatInstant(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) {
    return iso;
  }
  const pad = (value: number): string => String(value).padStart(2, "0");
  return (
    `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())} ` +
    `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}Z`
  );
}

export function formatDate(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) {
    return iso;
  }
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}`;
}
