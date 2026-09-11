import Link from "next/link";
import type { ReactNode } from "react";

export default function NotFound(): ReactNode {
  return (
    <div className="panel px-4 py-6">
      <p className="font-semibold">No such screen.</p>
      <p className="text-muted mt-1">
        The console has three: the board, the comparison and the audit trail.
      </p>
      <Link href="/" className="btn mt-3 inline-block">
        Back to the board
      </Link>
    </div>
  );
}
