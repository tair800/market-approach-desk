import type { ReactNode } from "react";

import { Board } from "@/components/Board";

export default function BoardPage(): ReactNode {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-base font-semibold">Board</h1>
        <p className="text-muted mt-0.5 max-w-3xl">
          Every open placement and the carrier panel behind it. One row is one approach —{" "}
          <span className="text-text">one carrier at one stage</span>, which is the business identity
          the database holds unique. A carrier may appear twice only under two different stages.
        </p>
      </div>
      <Board />
    </div>
  );
}
