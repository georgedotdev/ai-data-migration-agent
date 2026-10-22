import { useEffect, useRef, useState } from "react";
import { Bot, BrainCircuit, CheckCircle2, Download, KeyRound, Play, RefreshCw, RotateCcw, Sparkles, XCircle } from "lucide-react";
import { api } from "../api";
import { EndpointPicker, SystemGlyph } from "../components/EndpointPicker";
import type { AgentView, AppConfig, DslStep, EndpointSpec } from "../types";
import { Alert, Badge, Button, Card, CodeBlock, Collapsible, DataTable, Field, Metric, cx, usePersistentState } from "../components/ui";

const STEPS = ["Configure", "AI plans", "Human review", "Execute & report"];

export function AgentPage({ config }: { config: AppConfig }) {
  const preset = config.presets[0];
  const [source, setSource] = usePersistentState<EndpointSpec>("ag.source", { kind: "csv", config: { preset: preset.id }, table: null });
  const [target, setTarget] = usePersistentState<EndpointSpec>("ag.target", { kind: "sqlite", config: {}, table: "employees_ai" });
  const [provider, setProvider] = usePersistentState("ag.provider", "Auto");
  const [model, setModel] = usePersistentState("ag.model", "");
  const [goal, setGoal] = usePersistentState("ag.goal", "Clean this legacy table and migrate it. Keep the ID column as the key.");
  const [keys, setKeys] = usePersistentState<Record<string, string>>("ag.keys", {}, sessionStorage);
  const [view, setView] = useState<AgentView | null>(null);
  const [busy, setBusy] = useState<"" | "start" | "approve" | "replan">("");
  const [error, setError] = useState("");
  const [rejected, setRejected] = useState<Set<number>>(new Set());
  const [feedback, setFeedback] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const topRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (view) topRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [view?.status, view?.thread_id]);

  useEffect(() => {
    if (!busy) return;
    setElapsed(0);
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, [busy]);

  const prov = config.ai.providers.find((p) => p.name === provider);
  const activeStep = !view ? (busy === "start" ? 1 : 0) : view.status === "paused" ? 2 : 3;

  const start = async () => {
    setBusy("start"); setError(""); setView(null); setRejected(new Set()); setFeedback("");
    try {
      setView(await api.agentStart({ source, target, provider, model: provider === "Auto" || provider === "Deterministic" ? "" : model, goal, api_keys: keys }));
    } catch (e: any) { setError(e.message); } finally { setBusy(""); }
  };
  const resume = async (approved: boolean) => {
    if (!view) return;
    setBusy(approved ? "approve" : "replan"); setError("");
    try {
      const v = await api.agentResume(view.thread_id, { approved, feedback, rejected_steps: Array.from(rejected), api_keys: keys });
      setView(v);
      if (!approved) setRejected(new Set());
    } catch (e: any) { setError(e.message); } finally { setBusy(""); }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-50"><Bot className="h-6 w-6 text-accent" /> AI Agent</h1>
        <p className="mt-1 text-sm text-slate-400">An LLM profiles the data and recommends cleaning steps in a restricted DSL. You approve or reject each step; only approved steps run. The LLM never executes code or SQL.</p>
      </div>

      <ol className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {STEPS.map((s, i) => (
          <li key={s} className={cx("flex items-center gap-2 rounded-xl border px-3 py-2 text-sm",
            i < activeStep ? "border-accent/30 text-accent" : i === activeStep ? "border-accent/60 bg-accent-soft text-slate-100" : "border-ink-700 text-slate-500")}>
            <span className={cx("flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold", i <= activeStep ? "bg-accent text-ink-950" : "bg-ink-800")}>
              {i < activeStep ? "✓" : i + 1}
            </span>
            {s}
          </li>
        ))}
      </ol>

      {!view && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Source" icon={<SystemGlyph kind={source.kind} size="sm" />}>
              <EndpointPicker role="source" systems={config.systems} value={source} onChange={setSource} preset={preset} />
            </Card>
            <Card title="Target" icon={<SystemGlyph kind={target.kind} size="sm" />}>
              <EndpointPicker role="target" systems={config.systems} value={target} onChange={setTarget} preset={{ ...preset, target: "employees_ai" }} />
            </Card>
          </div>

          <Card title="Planner" subtitle="Which model writes the cleaning plan" icon={<BrainCircuit className="h-4 w-4" />}>
            <div className="grid gap-4 md:grid-cols-3">
              <Field label="Provider">
                <select className="input" value={provider} onChange={(e) => { setProvider(e.target.value); setModel(config.ai.providers.find((p) => p.name === e.target.value)?.default_model ?? ""); }}>
                  <option value="Auto">Auto (first available)</option>
                  {config.ai.providers.map((p) => <option key={p.name} value={p.name}>{p.name}{p.server_key ? "" : " (needs key)"}</option>)}
                  <option value="Deterministic">Rule-based (no LLM)</option>
                </select>
              </Field>
              <Field label="Model">
                <select className="input" value={model} disabled={!prov} onChange={(e) => setModel(e.target.value)}>
                  {prov ? prov.models.map((m) => <option key={m}>{m}</option>) : <option value="">automatic</option>}
                </select>
              </Field>
              <Field label="Server keys">
                <div className="flex flex-wrap gap-1.5 pt-1.5">
                  {config.ai.providers.map((p) => <Badge key={p.name} tone={p.server_key || keys[p.name] ? "good" : "neutral"}>{p.name} {p.server_key ? "✓" : keys[p.name] ? "(session)" : "—"}</Badge>)}
                </div>
              </Field>
              <div className="md:col-span-3">
                <Field label="Migration goal (sent to the LLM)"><textarea className="input min-h-[70px]" value={goal} onChange={(e) => setGoal(e.target.value)} /></Field>
              </div>
            </div>
            <div className="mt-4">
              <Collapsible title={<span className="flex items-center gap-2"><KeyRound className="h-4 w-4" /> Use your own API keys (kept in this browser tab only)</span>}>
                <div className="grid gap-3 md:grid-cols-3">
                  {config.ai.providers.map((p) => (
                    <Field key={p.name} label={`${p.name} key`}>
                      <input className="input" type="password" autoComplete="off" value={keys[p.name] ?? ""} onChange={(e) => setKeys({ ...keys, [p.name]: e.target.value })} />
                    </Field>
                  ))}
                </div>
              </Collapsible>
            </div>
          </Card>

          <div className="flex justify-center">
            <Button variant="primary" onClick={start} loading={busy === "start"} className="px-8 py-3 text-base"><Sparkles className="h-5 w-5" /> Analyze & plan</Button>
          </div>
          {busy === "start" && <Thinking elapsed={elapsed} provider={provider} />}
        </>
      )}

      <div ref={topRef} className="scroll-mt-20" />
      {error && <Alert tone="bad" title="Something went wrong">{error}</Alert>}

      {view && <AgentRun view={view} rejected={rejected} setRejected={setRejected} feedback={feedback} setFeedback={setFeedback}
        busy={busy} elapsed={elapsed} onApprove={() => resume(true)} onReplan={() => resume(false)} onReset={() => { setView(null); setError(""); }} />}
    </div>
  );
}

function Thinking({ elapsed, provider }: { elapsed: number; provider: string }) {
  const stage = elapsed < 3 ? "Profiling the source data" : elapsed < 6 ? `Asking ${provider === "Auto" ? "the LLM" : provider} for a plan` : "Waiting for the LLM (large structured answers can take up to a minute)";
  return (
    <div className="flex items-center justify-center gap-3 text-sm text-slate-400">
      <span className="relative flex h-3 w-3"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" /><span className="relative inline-flex h-3 w-3 rounded-full bg-accent" /></span>
      {stage}… <span className="tabular-nums text-slate-500">{elapsed}s</span>
    </div>
  );
}

function AgentRun({ view, rejected, setRejected, feedback, setFeedback, busy, elapsed, onApprove, onReplan, onReset }: {
  view: AgentView; rejected: Set<number>; setRejected: (s: Set<number>) => void; feedback: string; setFeedback: (s: string) => void;
  busy: string; elapsed: number; onApprove: () => void; onReplan: () => void; onReset: () => void;
}) {
  const s = view.state;
  const dsl = s.transformation_dsl ?? {};
  const meta = dsl._metadata ?? {};
  const steps = dsl.transformations ?? [];
  const p = s.profile ?? {};
  const imp = s.preview_impact ?? {};
  const paused = view.status === "paused";

  return (
    <div className="space-y-5">
      {dsl.fallback_reason ? (
        <Alert tone="warn" title="No LLM was used: this plan comes from the rule-based planner">{dsl.fallback_reason}</Alert>
      ) : (
        <Alert tone="accent" title={<span className="flex items-center gap-2"><BrainCircuit className="h-4 w-4" /> Plan written by {meta.provider_used} · <code>{meta.model_used}</code></span>}>
          {meta.fallback_chain && meta.fallback_chain.length > 1 ? `Tried: ${meta.fallback_chain.join(" → ")}. ` : ""}Nothing runs until you approve.
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label="Rows" value={p.row_count ?? "–"} />
        <Metric label="Columns" value={p.column_count ?? "–"} />
        <Metric label="Duplicate rows" value={p.duplicate_rows ?? "–"} />
        <Metric label="Quality score" value={`${p.data_quality_score ?? "–"}%`} tone={(p.data_quality_score ?? 0) > 90 ? "good" : "bad"} />
      </div>

      {s.assessment?.dataset_assessment && (
        <Card title="AI assessment" icon={<Bot className="h-4 w-4" />}>
          <p className="text-sm text-slate-300">{s.assessment.dataset_assessment}</p>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <List title="Issues found" items={s.assessment.identified_issues} />
            <List title="Schema recommendations" items={s.assessment.schema_mapping_recommendations} />
          </div>
        </Card>
      )}

      <Collapsible title="Column profile">
        <DataTable data={{
          columns: ["column", "type", "missing %", "unique", "suspected placeholders"],
          rows: Object.entries(p.columns ?? {}).map(([c, v]: [string, any]) => [c, v.dtype, v.missing_pct, v.unique_count, (v.suspected_sentinels ?? []).join(", ")]),
        }} />
      </Collapsible>

      {Object.keys(imp).length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="Rows (preview)" value={`${imp.rows_before} → ${imp.rows_after}`} />
          <Metric label="Duplicates removed" value={imp.duplicates_removed ?? 0} />
          <Metric label="Quality before" value={`${imp.quality_score_before ?? "–"}%`} />
          <Metric label="Quality after" value={`${imp.quality_score_after ?? "–"}%`} tone="accent" hint={imp.improvement_pct !== undefined ? `${imp.improvement_pct >= 0 ? "+" : ""}${imp.improvement_pct}%` : undefined} />
        </div>
      )}

      <Card title={`Recommended plan · ${steps.length} steps`} subtitle={paused ? `${steps.length - rejected.size} approved · ${rejected.size} rejected. Untick anything you disagree with.` : "Plan as executed"}
        action={s.risk?.overall_confidence !== undefined && <Badge tone="info">confidence {s.risk.overall_confidence}%</Badge>}>
        <ol className="space-y-2">
          {steps.map((st, i) => (
            <StepRow key={i} i={i} step={st} reason={dsl.reasoning?.[i]?.reason} samples={s.preview?.[i]?.samples}
              included={!rejected.has(i)} editable={paused}
              toggle={() => { const n = new Set(rejected); n.has(i) ? n.delete(i) : n.add(i); setRejected(n); }} />
          ))}
        </ol>
      </Card>

      {paused && (
        <Card title="Human review" subtitle="The workflow is paused before execution (LangGraph interrupt)">
          <Field label="Feedback for the AI (optional; used when re-planning)">
            <input className="input" value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="e.g. Don't fill missing emails; keep duplicate rows" />
          </Field>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="primary" onClick={onApprove} loading={busy === "approve"}><Play className="h-4 w-4" /> Approve {steps.length - rejected.size} steps & execute</Button>
            <Button onClick={onReplan} loading={busy === "replan"} disabled={!feedback}><RefreshCw className="h-4 w-4" /> Re-plan with feedback</Button>
            <Button variant="ghost" onClick={onReset}><RotateCcw className="h-4 w-4" /> Start over</Button>
            {busy === "replan" && <span className="self-center text-xs text-slate-500">{elapsed}s</span>}
          </div>
        </Card>
      )}

      {view.status === "finished" && <Finished view={view} onReset={onReset} />}
    </div>
  );
}

function StepRow({ i, step, reason, samples, included, editable, toggle }: {
  i: number; step: DslStep; reason?: string; samples?: Record<string, unknown>[]; included: boolean; editable: boolean; toggle: () => void;
}) {
  const [open, setOpen] = useState(false);
  const params = Object.entries(step).filter(([k, v]) => !["action", "column", "confidence"].includes(k) && v !== null && v !== undefined && v !== "");
  const conf = step.confidence;
  return (
    <li className={cx("rounded-xl border px-3 py-2.5 transition", included ? "border-ink-700 bg-ink-900/60" : "border-rose-500/20 bg-rose-500/[0.04] opacity-60")}>
      <div className="flex flex-wrap items-center gap-3">
        {editable && (
          <button onClick={toggle} className={cx("relative h-5 w-9 rounded-full transition", included ? "bg-accent" : "bg-ink-600")} title={included ? "Reject this step" : "Approve this step"}>
            <span className={cx("absolute top-0.5 h-4 w-4 rounded-full bg-white transition", included ? "left-4" : "left-0.5")} />
          </button>
        )}
        <span className="w-6 text-xs tabular-nums text-slate-500">{i + 1}</span>
        <Badge tone="accent">{step.action}</Badge>
        {step.column && <code className="text-xs text-slate-300">{step.column}</code>}
        {params.map(([k, v]) => <span key={k} className="text-xs text-slate-500">{k}=<span className="text-slate-300">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span></span>)}
        <span className="flex-1" />
        {!included && <Badge tone="bad">rejected</Badge>}
        {conf !== undefined && <Badge tone={conf < 70 ? "bad" : conf < 90 ? "warn" : "good"}>{conf}%</Badge>}
        {samples && samples.length > 0 && <button onClick={() => setOpen(!open)} className="text-xs text-accent hover:underline">{open ? "hide" : "preview"}</button>}
      </div>
      {reason && <p className="mt-1.5 pl-[3.25rem] text-xs text-slate-400">{reason}</p>}
      {open && samples && (
        <div className="mt-2 pl-[3.25rem]">
          <DataTable maxHeight={200} data={{ columns: Object.keys(samples[0]), rows: samples.map((r) => Object.values(r)) }}
            highlight={(c) => (c === "before" ? "bg-rose-500/[0.07]" : c === "after" ? "bg-emerald-500/[0.07]" : undefined)} />
        </div>
      )}
    </li>
  );
}

function Finished({ view, onReset }: { view: AgentView; onReset: () => void }) {
  const s = view.state;
  const rec = s.reconciliation ?? {};
  const log = s.execution_log ?? [];
  const ok = s.success && rec.overall_success;
  const executed = log.filter((l) => l.status === "success").length;
  const report = s.report ?? {};
  const impact = report.impact ?? {};
  const read = Number(rec.rows_read ?? 0), written = Number(rec.rows_written ?? 0);

  const download = (name: string, text: string, type: string) => {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
  };
  const markdown = `# ${report.project_name ?? "Migration report"}\n\n- Source: \`${report.source}\`\n- Target: \`${report.target}\`\n- Status: ${ok ? "SUCCESS" : "FAILED"}\n- Planner: ${s.provider_used} (${s.model_used})\n- Steps executed: ${executed}/${log.length}\n- Rows: ${read} read, ${written} written\n- Quality: ${impact.quality_score_before ?? "?"}% → ${impact.quality_score_after ?? "?"}%\n\n## Execution log\n${log.map((l) => `- ${l.action}: ${l.status}`).join("\n")}\n`;

  return (
    <div className="space-y-5">
      <div className={cx("rounded-2xl border p-5", ok ? "border-emerald-500/30 bg-emerald-500/[0.06]" : "border-rose-500/30 bg-rose-500/[0.06]")}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            {ok ? <CheckCircle2 className="h-7 w-7 text-emerald-300" /> : <XCircle className="h-7 w-7 text-rose-300" />}
            <div>
              <div className="text-lg font-semibold text-slate-100">{ok ? "Migration complete" : "Migration failed or rolled back"}</div>
              <div className="text-sm text-slate-400">{s.source_type} → {s.target_type} · <code>{s.table_name}</code></div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => download("migration_report.json", JSON.stringify(report, null, 2), "application/json")}><Download className="h-4 w-4" /> JSON</Button>
            <Button onClick={() => download("migration_report.md", markdown, "text/markdown")}><Download className="h-4 w-4" /> Markdown</Button>
            {s.database_download && <a href={api.agentDbUrl(view.thread_id)}><Button variant="primary"><Download className="h-4 w-4" /> Database file</Button></a>}
            <Button variant="ghost" onClick={onReset}><RotateCcw className="h-4 w-4" /> New run</Button>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="Rows read" value={read} />
          <Metric label="Rows written" value={written} tone="accent" />
          <Metric label="Steps executed" value={`${executed}/${log.length}`} tone={executed === log.length ? "good" : undefined} />
          <Metric label="Quality" value={`${impact.quality_score_after ?? "–"}%`} hint={impact.quality_score_before !== undefined ? `from ${impact.quality_score_before}%` : undefined} />
        </div>
      </div>

      <Card title="Execution log" subtitle={(s.executed_steps ?? []).join(" → ")}>
        <ul className="space-y-1.5">
          {log.map((l, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
              {l.status === "success" ? <CheckCircle2 className="h-4 w-4 text-emerald-300" /> : <XCircle className="h-4 w-4 text-rose-300" />}
              <code className="text-slate-200">{l.action}</code>
              {l.status !== "success" && <span className="text-xs text-rose-300">{l.reason ?? l.details?.error ?? l.status}</span>}
            </li>
          ))}
        </ul>
        {(s.quarantine_report ?? []).length > 0 && (
          <div className="mt-4">
            <Alert tone="warn" title="Values that could not be parsed became NULL">
              {(s.quarantine_report ?? []).map((q, i) => <div key={i}><code>{q.column}</code>: {q.rows_affected} values via <code>{q.action}</code></div>)}
            </Alert>
          </div>
        )}
      </Card>

      <Collapsible title="AI forensics: raw prompt, raw response, parsed plan">
        <div className="space-y-3">
          <div className="label">Raw prompt</div><CodeBlock code={s.raw_prompt ?? ""} />
          <div className="label">Raw LLM response</div><CodeBlock code={s.raw_ai_response ?? ""} />
          <div className="label">Parsed DSL</div><CodeBlock code={JSON.stringify(s.transformation_dsl ?? {}, null, 2)} />
        </div>
      </Collapsible>
    </div>
  );
}

function List({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <div className="label">{title}</div>
      <ul className="space-y-1 text-sm text-slate-300">{items.map((x, i) => <li key={i} className="flex gap-2"><span className="text-accent">•</span>{x}</li>)}</ul>
    </div>
  );
}
