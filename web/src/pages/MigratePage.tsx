import { useEffect, useRef, useState } from "react";
import { ArrowRight, Bug, Rocket } from "lucide-react";
import { api } from "../api";
import { EndpointPicker, SystemGlyph, defaultTable } from "../components/EndpointPicker";
import { MigrationResult } from "../components/MigrationResult";
import type { AppConfig, EndpointSpec, MigrationResult as Result, Preset } from "../types";
import { Alert, Button, Card, Collapsible, DataTable, Field, Segmented, Skeleton, cx, usePersistentState } from "../components/ui";

export function MigratePage({ config }: { config: AppConfig }) {
  const [presetId, setPresetId] = usePersistentState("mg.preset", config.presets[0].id);
  const preset = config.presets.find((p) => p.id === presetId) ?? config.presets[0];
  const [source, setSource] = usePersistentState<EndpointSpec>("mg.source", { kind: "postgresql", config: {}, table: preset.id });
  const [target, setTarget] = usePersistentState<EndpointSpec>("mg.target", { kind: "mysql", config: {}, table: preset.target });
  const [mode, setMode] = usePersistentState<"flat" | "3nf">("mg.mode", "flat");
  const [norm, setNorm] = usePersistentState("mg.norm", { column: preset.normalize_column, lookup: preset.lookup_table });
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<{ message: string; log?: unknown } | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (result || error) resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [result, error]);

  const pickPreset = (p: Preset) => {
    setPresetId(p.id);
    setSource((s) => ({ ...s, table: defaultTable(s.kind, "source", p), config: s.kind === "csv" && !s.config.upload_id ? { preset: p.id } : s.config }));
    setTarget((t) => ({ ...t, table: p.target }));
    setNorm({ column: p.normalize_column, lookup: p.lookup_table });
  };

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.migrate({
        source, target,
        normalize_column: mode === "3nf" ? norm.column : null,
        lookup_table: mode === "3nf" ? norm.lookup : null,
      });
      if (r.status === "error") setError({ message: r.message, log: (r as any).transformation_log });
      else setResult(r);
    } catch (e: any) {
      setError({ message: e.message });
    } finally {
      setRunning(false);
    }
  };

  const srcLabel = config.systems.find((s) => s.kind === source.kind)?.label;
  const tgtLabel = config.systems.find((s) => s.kind === target.kind)?.label;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-50">Migrate</h1>
        <p className="mt-1 text-sm text-slate-400">
          Clean a dirty legacy table, design a constrained schema for the target, load it atomically, and prove the result with live queries.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {config.presets.map((p) => (
          <button key={p.id} onClick={() => pickPreset(p)}
            className={cx("rounded-2xl border p-4 text-left transition",
              p.id === preset.id ? "border-accent/60 bg-accent-soft shadow-glow" : "border-ink-700 bg-ink-850/70 hover:border-ink-600")}>
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-100">{p.label}</span>
              <span className="flex items-center gap-1 text-xs text-amber-300"><Bug className="h-3.5 w-3.5" />{p.defect_total} defects · {p.rows} rows</span>
            </div>
            <p className="mt-1 text-xs text-slate-400">{p.blurb}</p>
          </button>
        ))}
      </div>
      <Collapsible title={<span>What's wrong with <code className="text-accent">{preset.id}</code>: injected defect inventory</span>}>
        <DataTable data={{ columns: ["defect", "rows affected", "example"], rows: preset.defects.map((d) => [d.defect, d.count, d.example]) }} maxHeight={300} />
      </Collapsible>

      <div className="grid items-start gap-4 lg:grid-cols-[1fr_auto_1fr]">
        <Card title="Source" subtitle="Legacy system to read from" icon={<SystemGlyph kind={source.kind} size="sm" />}>
          <EndpointPicker role="source" systems={config.systems} value={source} onChange={setSource} preset={preset} />
        </Card>
        <div className="hidden h-full items-center justify-center lg:flex">
          <div className="rounded-full border border-ink-600 bg-ink-850 p-2.5 text-accent"><ArrowRight className="h-5 w-5" /></div>
        </div>
        <Card title="Target" subtitle="Where the clean, constrained data goes" icon={<SystemGlyph kind={target.kind} size="sm" />}>
          <div className="space-y-5">
            <EndpointPicker role="target" systems={config.systems} value={target} onChange={setTarget} preset={preset} />
            <div className="space-y-3 border-t border-ink-700/60 pt-4">
              <div className="flex items-center justify-between gap-3">
                <span className="label !mb-0">Schema</span>
                <Segmented value={mode} onChange={setMode} options={[{ id: "flat", label: "Flat table" }, { id: "3nf", label: "Normalized (3NF)" }]} />
              </div>
              {mode === "3nf" && (
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Column to extract"><input className="input font-mono" value={norm.column} onChange={(e) => setNorm({ ...norm, column: e.target.value })} /></Field>
                  <Field label="Lookup table"><input className="input font-mono" value={norm.lookup} onChange={(e) => setNorm({ ...norm, lookup: e.target.value })} /></Field>
                </div>
              )}
            </div>
          </div>
        </Card>
      </div>

      <div className="flex justify-center">
        <Button variant="primary" onClick={run} loading={running} className="px-8 py-3 text-base">
          <Rocket className="h-5 w-5" /> Migrate {srcLabel} → {tgtLabel}
        </Button>
      </div>

      {running && (
        <div className="space-y-3">
          <div className="text-center text-sm text-slate-400">Extracting → cleaning → designing schema → loading atomically → verifying…</div>
          <Skeleton className="h-36" /><Skeleton className="h-12" /><Skeleton className="h-64" />
        </div>
      )}
      <div ref={resultRef} className="scroll-mt-20" />
      {error && (
        <Alert tone="bad" title="Migration failed">
          {error.message}
          {/rolled back|untouched/.test(error.message) && <div className="mt-1 text-slate-400">The load is atomic, so the existing target tables were not modified.</div>}
        </Alert>
      )}
      {result && <MigrationResult res={result} />}
    </div>
  );
}
