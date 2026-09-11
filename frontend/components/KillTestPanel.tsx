"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { EmptyPanel } from "@/components/panels";
import { armVerdict, duplicates, parseKillTest, type ArmResult, type KillTestResult } from "@/lib/killtest";
import { formatInstant } from "@/lib/states";

/**
 * The comparison, read from `public/killtest.json`.
 *
 * Fetched from the static path rather than read off disk so the file the browser sees is the file
 * the run wrote, on a platform that serves `public/` from a CDN as readily as from local disk. A
 * 404 is the ordinary state of a fresh clone, not an error: the kill test has not been run.
 */

type Load =
  | { status: "loading" }
  | { status: "absent" }
  | { status: "unreadable" }
  | { status: "ready"; result: KillTestResult };

function Arm({
  arm,
  name,
  mechanism,
}: {
  arm: ArmResult;
  name: string;
  mechanism: string;
}): ReactNode {
  const verdict = armVerdict(arm);
  const extra = duplicates(arm);

  return (
    <section className="panel flex flex-col" data-testid={`arm-${name.toLowerCase()}`}>
      <header className="panel-head px-4 py-2.5">
        <h3 className="font-semibold">{name}</h3>
        <p className="text-dim mt-0.5">{mechanism}</p>
      </header>
      <div className="grid grid-cols-3 gap-px bg-[var(--color-line-soft)]">
        <div className="bg-panel px-4 py-3">
          <div className="text-dim text-[10px] font-semibold tracking-[0.08em] uppercase">
            Observed
          </div>
          <div className="mt-0.5 text-2xl font-semibold tabular-nums">{arm.observed}</div>
        </div>
        <div className="bg-panel px-4 py-3">
          <div className="text-dim text-[10px] font-semibold tracking-[0.08em] uppercase">
            Distinct keys
          </div>
          <div className="mt-0.5 text-2xl font-semibold tabular-nums">{arm.distinct_keys}</div>
        </div>
        <div className="bg-panel px-4 py-3">
          <div className="text-dim text-[10px] font-semibold tracking-[0.08em] uppercase">
            Duplicates
          </div>
          <div
            className={`mt-0.5 text-2xl font-semibold tabular-nums ${
              extra > 0 ? "text-[#ff8f9b]" : "text-[#5fd6a4]"
            }`}
            data-testid={`duplicates-${name.toLowerCase()}`}
          >
            {extra}
          </div>
        </div>
      </div>
      <p
        className={`border-t border-[var(--color-line)] px-4 py-2.5 font-medium ${
          verdict.ok ? "text-[#5fd6a4]" : "text-[#ff8f9b]"
        }`}
        data-testid={`verdict-${name.toLowerCase()}`}
      >
        {verdict.text}
      </p>
    </section>
  );
}

export function KillTestView({ result }: { result: KillTestResult }): ReactNode {
  return (
    <div className="flex flex-col gap-4" data-testid="killtest-view">
      <div className="panel flex flex-wrap items-baseline gap-x-6 gap-y-1 px-4 py-2.5">
        <span className="text-dim text-[10px] font-semibold tracking-[0.08em] uppercase">
          Identity under test
        </span>
        <span className="mono text-text">{result.identity}</span>
        <span className="text-dim ml-auto">ran {formatInstant(result.ran_at)}</span>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Arm
          arm={result.n8n}
          name="n8n"
          mechanism="Read the due-set, decide, send, then write. No transaction."
        />
        <Arm
          arm={result.python}
          name="Python"
          mechanism="Claim inside one transaction, with every eligibility rule inside it."
        />
      </div>
      <p className="text-dim">
        Counts come from the fake carrier receiver, keyed on the business identity — never from this
        system&rsquo;s own tables. A system that grades itself from its own records is not measuring
        anything.
      </p>
    </div>
  );
}

export function KillTestPanel(): ReactNode {
  const [load, setLoad] = useState<Load>({ status: "loading" });

  const read = useCallback(async () => {
    setLoad({ status: "loading" });
    try {
      const response = await fetch("/killtest.json", { cache: "no-store" });
      if (response.status === 404) {
        setLoad({ status: "absent" });
        return;
      }
      if (!response.ok) {
        setLoad({ status: "unreadable" });
        return;
      }
      const payload: unknown = await response.json().catch(() => null);
      const result = parseKillTest(payload);
      setLoad(result ? { status: "ready", result } : { status: "unreadable" });
    } catch {
      setLoad({ status: "absent" });
    }
  }, []);

  useEffect(() => {
    void read();
  }, [read]);

  if (load.status === "loading") {
    return (
      <div className="panel px-4 py-6 text-muted" role="status" data-testid="loading-panel">
        Reading the last kill-test run…
      </div>
    );
  }

  if (load.status === "absent") {
    return (
      <EmptyPanel title="The kill test has not been run in this checkout.">
        Run <code className="mono text-text">make killtest</code>. It executes both arms against one
        harness and one fake carrier receiver, then writes{" "}
        <code className="mono text-text">frontend/public/killtest.json</code>, which this screen
        renders. Nothing is shown here until a run produces it — a committed result would be a
        number this console asserts rather than one a run measured.
      </EmptyPanel>
    );
  }

  if (load.status === "unreadable") {
    return (
      <EmptyPanel title="The published result could not be read.">
        <code className="mono text-text">public/killtest.json</code> exists but is not in the shape
        this screen expects. Re-run <code className="mono text-text">make killtest</code> rather
        than editing it by hand.
      </EmptyPanel>
    );
  }

  return <KillTestView result={load.result} />;
}
