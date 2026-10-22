import { ArrowRight, KeyRound, Link2 } from "lucide-react";
import type { MigrationResult } from "../types";

function TableCard({ name, rows }: { name: string; rows: unknown[][] }) {
  return (
    <div className="min-w-[230px] overflow-hidden rounded-xl border border-ink-600 bg-ink-900">
      <div className="border-b border-ink-700 bg-gradient-to-r from-accent/20 to-transparent px-3 py-2 font-mono text-sm font-semibold text-slate-100">{name}</div>
      <ul className="divide-y divide-ink-800 text-xs">
        {rows.map((r, i) => {
          const [col, type, nullable, key] = r as [string, string, string, string];
          return (
            <li key={i} className="flex items-center justify-between gap-4 px-3 py-1.5">
              <span className="flex items-center gap-1.5 font-mono text-slate-200">
                {key === "PK" ? <KeyRound className="h-3 w-3 text-amber-300" /> : key === "FK" ? <Link2 className="h-3 w-3 text-sky-300" /> : <span className="w-3" />}
                {col}
              </span>
              <span className="font-mono text-slate-500">{String(type).replace(/"/g, "")}{nullable === "NO" && key !== "PK" ? " ·" : ""}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function ErDiagram({ res }: { res: MigrationResult }) {
  const main = res.target_info[res.target_table];
  const lookup = res.lookup_table ? res.target_info[res.lookup_table] : null;
  return (
    <div className="flex flex-wrap items-start gap-4 overflow-x-auto rounded-xl border border-ink-700/80 bg-ink-950/60 p-5">
      {main && <TableCard name={res.target_table} rows={main.columns.rows} />}
      {lookup && res.lookup_table && (
        <>
          <div className="mt-12 flex flex-col items-center gap-1 text-xs text-slate-400">
            <span className="font-mono text-sky-300">{res.normalize_column}_id → id</span>
            <div className="flex items-center gap-1">
              <span className="h-px w-16 bg-sky-400/60" />
              <ArrowRight className="h-4 w-4 text-sky-400" />
            </div>
            <span>many-to-one</span>
          </div>
          <TableCard name={res.lookup_table} rows={lookup.columns.rows} />
        </>
      )}
      <div className="w-full text-xs text-slate-500">
        <KeyRound className="mr-1 inline h-3 w-3 text-amber-300" />primary key
        <Link2 className="mx-1 ml-4 inline h-3 w-3 text-sky-300" />foreign key
        <span className="ml-4">· = NOT NULL</span>
      </div>
    </div>
  );
}
