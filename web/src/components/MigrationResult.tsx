import { useState } from "react";
import { CheckCircle2, ChevronRight, Download, Play, ShieldCheck, XCircle } from "lucide-react";
import { api } from "../api";
import type { MigrationResult as Result, Table } from "../types";
import { ErDiagram } from "./ErDiagram";
import { Alert, Badge, Button, Card, CodeBlock, DataTable, Metric, Tabs, cx } from "./ui";

type Tab = "proof" | "schema" | "cleaning" | "data" | "history";

export function MigrationResult({ res }: { res: Result }) {
  const [tab, setTab] = useState<Tab>("proof");
  const passed = res.checks.filter((c) => c.passed).length;
  const ok = res.status === "success";
  const s = res.stats;
  const pct = (n: number) => `${(100 * n) / Math.max(s.source_rows, 1)}%`;

  return (
    <div className="space-y-5">
      <div className={cx("rounded-2xl border p-5", ok ? "border-emerald-500/30 bg-emerald-500/[0.06]" : "border-rose-500/30 bg-rose-500/[0.06]")}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            {ok ? <ShieldCheck className="h-7 w-7 text-emerald-300" /> : <XCircle className="h-7 w-7 text-rose-300" />}
            <div>
              <div className="text-lg font-semibold text-slate-100">{ok ? "Migration verified" : "Loaded, but verification failed"}</div>
              <div className="text-sm text-slate-400">{res.message}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone="neutral">run #{res.run_id}</Badge>
            <Badge tone={ok ? "good" : "bad"}>{passed}/{res.checks.length} checks</Badge>
            <a href={api.exportUrl(res.result_id)}><Button><Download className="h-4 w-4" /> CSV</Button></a>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-5">
          <Metric label={`Source · ${res.source_system}`} value={s.source_rows} />
          <Metric label={`Loaded · ${res.target_system}`} value={s.loaded_rows} tone="accent" />
          <Metric label="Duplicates removed" value={s.exact_duplicates_removed} />
          <Metric label="Quarantined" value={s.quarantined_rows} />
          <Metric label="Checks passed" value={`${passed}/${res.checks.length}`} tone={ok ? "good" : "bad"} />
        </div>

        <div className="mt-4">
          <div className="flex h-2.5 overflow-hidden rounded-full bg-ink-800">
            <div className="bg-accent" style={{ width: pct(s.loaded_rows) }} />
            <div className="bg-indigo-400" style={{ width: pct(s.exact_duplicates_removed) }} />
            <div className="bg-amber-400" style={{ width: pct(s.quarantined_rows) }} />
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
            <span>Row accounting: <b className="text-slate-200">{s.source_rows}</b> = <span className="text-accent">{s.loaded_rows} loaded</span> + <span className="text-indigo-300">{s.exact_duplicates_removed} duplicates</span> + <span className="text-amber-300">{s.quarantined_rows} quarantined</span></span>
            <span className="text-slate-500">{Object.entries(res.timings).map(([k, v]) => `${k} ${v}s`).join(" · ")}</span>
          </div>
        </div>
      </div>

      <Alert tone="info" title="Load protocol">{res.protocol}</Alert>

      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "proof", label: "Proof" }, { id: "schema", label: "Schema design" }, { id: "cleaning", label: "Cleaning & quarantine" },
        { id: "data", label: "Before / after" }, { id: "history", label: "Run history" },
      ]} />

      {tab === "proof" && <ProofTab res={res} />}
      {tab === "schema" && <SchemaTab res={res} />}
      {tab === "cleaning" && <CleaningTab res={res} />}
      {tab === "data" && (
        <div className="grid gap-5 xl:grid-cols-2">
          <Card title={`Raw source · ${res.source_system}`} subtitle={res.source_table}><DataTable data={res.source_preview} /></Card>
          <Card title={`Cleaned · ${res.target_system}`} subtitle={res.target_table}><DataTable data={res.target_preview} /></Card>
        </div>
      )}
      {tab === "history" && <Card title="Migration runs" subtitle={`migration_runs in ${res.target_system}`}><DataTable data={res.history} /></Card>}
    </div>
  );
}

function ProofTab({ res }: { res: Result }) {
  const [open, setOpen] = useState<number | null>(null);
  const [q, setQ] = useState(res.queries[0]?.name ?? "");
  const [out, setOut] = useState<Table | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const query = res.queries.find((x) => x.name === q);

  const runQuery = async () => {
    setBusy(true);
    setErr("");
    try {
      setOut(await api.query(res.result_id, q));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <Card title="Verification checks" subtitle={`Each check just ran against ${res.source_system} and ${res.target_system}. Click a row to see its query.`}>
        <ul className="divide-y divide-ink-800 overflow-hidden rounded-xl border border-ink-700/80">
          {res.checks.map((c, i) => (
            <li key={i}>
              <button onClick={() => setOpen(open === i ? null : i)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-ink-800/50">
                {c.passed ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-300" /> : <XCircle className="h-4 w-4 shrink-0 text-rose-300" />}
                <span className="flex-1 text-slate-200">{c.check}</span>
                <span className="hidden max-w-[40%] truncate font-mono text-xs text-slate-400 md:block" title={String(c.actual)}>{fmt(c.actual)}</span>
                <ChevronRight className={cx("h-4 w-4 text-slate-500 transition", open === i && "rotate-90")} />
              </button>
              {open === i && (
                <div className="space-y-2 bg-ink-950/40 px-4 pb-4 pt-1">
                  <div className="grid gap-2 text-xs sm:grid-cols-2">
                    <div><span className="text-slate-500">expected</span> <span className="font-mono text-slate-200">{fmt(c.expected)}</span></div>
                    <div><span className="text-slate-500">actual (from the database)</span> <span className="font-mono text-slate-200">{fmt(c.actual)}</span></div>
                  </div>
                  <CodeBlock code={c.sql} maxHeight={160} />
                </div>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <Card title={`Query ${res.target_system} live`} subtitle="Preset read-only queries against the migrated data">
        <div className="flex flex-wrap gap-2">
          {res.queries.map((x) => (
            <button key={x.name} onClick={() => { setQ(x.name); setOut(null); }}
              className={cx("rounded-lg border px-3 py-1.5 text-xs transition", q === x.name ? "border-accent/60 bg-accent-soft text-accent" : "border-ink-700 text-slate-400 hover:text-slate-200")}>
              {x.name}
            </button>
          ))}
        </div>
        {query && <div className="mt-3"><CodeBlock code={query.text} maxHeight={140} /></div>}
        <div className="mt-3 flex items-center gap-3">
          <Button variant="primary" onClick={runQuery} loading={busy}><Play className="h-4 w-4" /> Run</Button>
          {out && <span className="text-xs text-slate-400">{out.rows.length} rows returned</span>}
        </div>
        {err && <div className="mt-3"><Alert tone="bad">{err}</Alert></div>}
        {out && <div className="mt-3"><DataTable data={out} /></div>}
      </Card>
    </div>
  );
}

function SchemaTab({ res }: { res: Result }) {
  const deps = res.dependents || [];
  const col = res.normalize_column;
  return (
    <div className="space-y-5">
      {res.lookup_table && (
        deps.length ? (
          <Alert tone="accent" title="3NF decomposition">
            Functional dependency detected in the data: <code className="text-accent">{col} → {deps.join(", ")}</code>. In the flat table the key
            determined <code>{col}</code>, which determined <code>{deps.join(", ")}</code> (a transitive dependency), so the same value was repeated on every row.
            <code> {col}</code> and its dependents moved to <code>{res.lookup_table}</code>; <code>{res.target_table}</code> keeps only the foreign key <code>{col}_id</code>.
          </Alert>
        ) : (
          <Alert tone="accent" title="Reference table">
            No other column depends on <code>{col}</code>, so the flat table was already in 3NF. Moving <code>{col}</code> into <code>{res.lookup_table}</code> (UNIQUE)
            with a foreign key stores each value once and makes the database reject misspelled values.
          </Alert>
        )
      )}
      {res.target_kind === "mongodb" && res.lookup_table && <Alert tone="warn">MongoDB has no foreign keys: the reference is by id and orphans are checked with <code>$lookup</code>.</Alert>}

      <Card title="Entity-relationship diagram" subtitle="Columns and types as reported by the target database"><ErDiagram res={res} /></Card>

      <Card title="Type mapping" subtitle={`${res.source_system} → ${res.target_system}`}>
        <DataTable data={res.type_mapping} highlight={(c) => (c === "target_type" ? "text-accent" : undefined)} />
      </Card>

      {Object.entries(res.target_info).map(([t, m]) => (
        <Card key={t} title={<span className="font-mono">{t}</span>} subtitle={`Definition ${m.ddl_source}`}>
          <div className="grid gap-4 xl:grid-cols-2">
            <CodeBlock code={m.ddl} maxHeight={380} />
            <DataTable data={m.constraints} maxHeight={380} emptyText="No constraints reported" />
          </div>
        </Card>
      ))}

      {res.explain?.before && res.explain?.after && (
        <Card title="Index effect" subtitle="Query plan before and after creating the index">
          <CodeBlock code={res.explain.query ?? ""} maxHeight={80} />
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div><div className="label">Before index</div><DataTable data={rowsToTable(res.explain.before)} /></div>
            <div><div className="label">After index</div><DataTable data={rowsToTable(res.explain.after)} /></div>
          </div>
          {res.explain.note && <p className="mt-3 text-xs text-slate-400">{res.explain.note}</p>}
        </Card>
      )}
    </div>
  );
}

function CleaningTab({ res }: { res: Result }) {
  const log = res.transformation_log.filter((l) => l.action !== "standardize_column_name");
  return (
    <div className="space-y-5">
      <Card title="Cleaning decisions" subtitle={`${log.length} rules applied · every decision is also stored in migration_steps`}>
        <ul className="space-y-2">
          {log.map((l, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border border-ink-800 bg-ink-900/50 px-3 py-2 text-sm">
              <Badge tone={l.action.startsWith("quarantine") ? "warn" : l.action.includes("duplicate") ? "info" : "accent"}>{l.action.replace(/_/g, " ")}</Badge>
              <span className="font-mono text-xs text-slate-400">{l.column}</span>
              <span className="flex-1 text-slate-300">{l.detail}</span>
              {l.rows_affected > 0 && <span className="text-xs tabular-nums text-slate-500">{l.rows_affected} rows</span>}
            </li>
          ))}
        </ul>
      </Card>
      <Card title={`Quarantined rows (${res.quarantine.rows.length})`} subtitle="Rows that break key integrity are kept aside with their raw values, never silently dropped">
        <DataTable data={res.quarantine} emptyText="Nothing quarantined" />
      </Card>
    </div>
  );
}

function rowsToTable(rows: Record<string, unknown>[]): Table {
  const columns = Array.from(new Set(rows.flatMap((r) => Object.keys(r))));
  return { columns, rows: rows.map((r) => columns.map((c) => r[c])) };
}

function fmt(v: unknown) {
  return typeof v === "string" ? v : JSON.stringify(v);
}
