/**
 * The API's read contract, mirrored.
 *
 * These types are a transcription of the Pydantic view models in
 * `src/market_approach_desk/api.py` — `MarketView`, `ApproachView`, `PlacementView`, `AuditView`,
 * `MetaView` — and of the two plain dictionaries the stats endpoint returns. Nothing here is
 * computed: the API decides `follow_up_overdue` against one clock so the browser cannot disagree
 * with the server about whether a chase is late.
 *
 * `state`, `stage` and `reply_classification` stay `string` rather than unions on purpose. A server
 * that adds a state must not blank the console; the badge lookup degrades to an "unknown" badge
 * that shows the raw value instead.
 */

export interface MarketView {
  id: string;
  name: string;
  underwriter: string;
  within_placing_authority: boolean;
}

export interface ApproachView {
  id: string;
  market: MarketView;
  stage: string;
  state: string;
  attempt_count: number;
  blocked_reason: string | null;
  due_at: string | null;
  follow_up_at: string | null;
  sent_at: string | null;
  /** Server-decided. True only while an approach is `sent` and its follow-up time has passed. */
  follow_up_overdue: boolean;
  reply_classification: string | null;
  reply_abstained: boolean;
}

export interface PlacementView {
  id: string;
  reference: string;
  insured_name: string;
  class_of_business: string;
  handler: string;
  /** ISO date, no time component. */
  inception_on: string;
  approaches: ApproachView[];
}

export interface AuditView {
  occurred_at: string;
  verb: string;
  /** The business identity as a string: `placement/market/stage`. */
  identity: string;
  actor: string;
  detail: string | null;
}

export interface StatsView {
  by_state: Record<string, number>;
  attempts: number;
}

export interface MetaView {
  version: string;
  demo_mode: boolean;
  /** Empty when the platform sets no revision variable. */
  revision: string;
}

/** What every `/api/console/*` route handler returns when it could not answer. */
export interface ConsoleError {
  kind: "unconfigured" | "unreachable" | "timeout" | "upstream" | "malformed";
  message: string;
}

export interface ConsoleErrorBody {
  error: ConsoleError;
}
