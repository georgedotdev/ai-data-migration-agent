import { useRef, useState } from "react";
import { FolderSearch, Plug, Sprout, Upload } from "lucide-react";
import { api } from "../api";
import type { EndpointSpec, Kind, Preset, SystemInfo } from "../types";
import { Badge, Button, Collapsible, Field, cx } from "./ui";

export const SYSTEM_STYLE: Record<Kind, { glyph: string; color: string }> = {
  postgresql: { glyph: "PG", color: "from-sky-500/30 to-sky-500/5 text-sky-300 border-sky-400/30" },
  mysql: { glyph: "My", color: "from-orange-500/30 to-orange-500/5 text-orange-300 border-orange-400/30" },
  duckdb: { glyph: "Du", color: "from-yellow-400/30 to-yellow-400/5 text-yellow-200 border-yellow-300/30" },
  sqlite: { glyph: "SQ", color: "from-indigo-500/30 to-indigo-500/5 text-indigo-300 border-indigo-400/30" },
  mongodb: { glyph: "Mg", color: "from-emerald-500/30 to-emerald-500/5 text-emerald-300 border-emerald-400/30" },
  csv: { glyph: "CSV", color: "from-slate-400/25 to-slate-400/5 text-slate-200 border-slate-400/30" },
};

export function SystemGlyph({ kind, size = "md" }: { kind: Kind; size?: "sm" | "md" }) {
  const s = SYSTEM_STYLE[kind];
  return (
    <span className={cx("inline-flex shrink-0 items-center justify-center rounded-lg border bg-gradient-to-br font-bold", s.color,
      size === "sm" ? "h-6 w-6 text-[10px]" : "h-9 w-9 text-xs")}>
      {s.glyph}
    </span>
  );
}

export function defaultTable(kind: Kind, role: "source" | "target", preset?: Preset) {
  if (kind === "csv") return null;
  if (!preset) return "";
  return role === "source" ? preset.id : preset.target;
}

export function EndpointPicker({ role, systems, value, onChange, preset, onUploaded }: {
  role: "source" | "target"; systems: SystemInfo[]; value: EndpointSpec; onChange: (v: EndpointSpec) => void;
  preset?: Preset; onUploaded?: (name: string) => void;
}) {
  const choices = systems.filter((s) => (role === "source" ? s.source : s.target));
  const sys = systems.find((s) => s.kind === value.kind);
  const [status, setStatus] = useState<{ ok: boolean; message: string } | null>(null);
  const [busy, setBusy] = useState<"" | "test" | "seed" | "tables" | "upload">("");
  const [tables, setTables] = useState<string[]>([]);
  const [uploadName, setUploadName] = useState<string>("");
  const fileRef = useRef<HTMLInputElement>(null);

  const setKind = (kind: Kind) => {
    setStatus(null);
    setTables([]);
    setUploadName("");
    onChange({ kind, config: kind === "csv" && preset ? { preset: preset.id } : {}, table: defaultTable(kind, role, preset) });
  };
  const setCfg = (k: string, v: string) => onChange({ ...value, config: { ...value.config, [k]: v } });
  const defaults = (role === "target" && sys?.target_defaults) || sys?.defaults || {};

  const run = async (what: "test" | "seed" | "tables") => {
    setBusy(what);
    try {
      if (what === "test") setStatus(await api.test(value, role));
      if (what === "seed") {
        const r = await api.seed(value, preset ? [preset.id] : undefined);
        setStatus({ ok: true, message: "Seeded " + Object.entries(r.seeded).map(([t, n]) => `${t} (${n} rows, all text)`).join(", ") });
      }
      if (what === "tables") {
        const r = await api.tables(value, role);
        setTables(r.tables);
        setStatus(r.error ? { ok: false, message: r.error } : { ok: true, message: `${r.tables.length} tables/collections found` });
      }
    } catch (e: any) {
      setStatus({ ok: false, message: e.message });
    } finally {
      setBusy("");
    }
  };

  const upload = async (f: File) => {
    setBusy("upload");
    try {
      const r = await api.upload(f);
      onChange({ ...value, config: { upload_id: r.upload_id } });
      setUploadName(r.filename);
      onUploaded?.(r.filename);
      setStatus({ ok: true, message: `Uploaded ${r.filename} (${r.columns.length} columns)` });
    } catch (e: any) {
      setStatus({ ok: false, message: e.message });
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {choices.map((s) => (
          <button key={s.kind} onClick={() => setKind(s.kind)}
            className={cx("flex flex-col items-center gap-1.5 rounded-xl border px-2 py-2.5 text-xs transition",
              value.kind === s.kind ? "border-accent/60 bg-accent-soft text-slate-100 shadow-glow" : "border-ink-700 bg-ink-900/60 text-slate-400 hover:border-ink-600 hover:text-slate-200")}>
            <SystemGlyph kind={s.kind} />
            {s.label.replace(" file", "")}
          </button>
        ))}
      </div>

      {value.kind === "csv" ? (
        <div className="space-y-2">
          <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => fileRef.current?.click()} loading={busy === "upload"}><Upload className="h-4 w-4" /> Upload CSV</Button>
            <span className="text-sm text-slate-400">
              {value.config.upload_id ? <>Using <b className="text-slate-200">{uploadName || "uploaded file"}</b></> : <>or use the demo file <b className="text-slate-200">{preset?.csv}</b></>}
            </span>
          </div>
        </div>
      ) : (
        <>
          <Field label={value.kind === "mongodb" ? "Collection" : "Table"}>
            <div className="flex gap-2">
              <input className="input font-mono" list={`${role}-tables`} value={value.table ?? ""} onChange={(e) => onChange({ ...value, table: e.target.value })} />
              <datalist id={`${role}-tables`}>{tables.map((t) => <option key={t} value={t} />)}</datalist>
              <Button variant="ghost" onClick={() => run("tables")} loading={busy === "tables"} title="List tables"><FolderSearch className="h-4 w-4" /></Button>
            </div>
          </Field>
          <Collapsible title={<span>Connection <span className="text-slate-500">· {describe(value, defaults)}</span></span>}>
            <ConnectionFields kind={value.kind} cfg={value.config} defaults={defaults} passwordSet={!!sys?.password_set} set={setCfg} />
          </Collapsible>
        </>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {value.kind !== "csv" && <Button onClick={() => run("test")} loading={busy === "test"}><Plug className="h-4 w-4" /> Test</Button>}
        {role === "source" && value.kind !== "csv" && (
          <Button onClick={() => run("seed")} loading={busy === "seed"} title="Load the dirty demo dataset into this system as a legacy all-text table">
            <Sprout className="h-4 w-4" /> Seed demo data
          </Button>
        )}
        {status && <Badge tone={status.ok ? "good" : "bad"} className="max-w-full whitespace-normal">{status.message}</Badge>}
      </div>
    </div>
  );
}

function describe(v: EndpointSpec, d: Record<string, string | number>) {
  const c = { ...d, ...Object.fromEntries(Object.entries(v.config).filter(([, x]) => x !== "")) };
  if (v.kind === "duckdb" || v.kind === "sqlite") return `runtime/${c.file}`;
  if (v.kind === "mongodb") return `${String(c.uri).replace(/^mongodb:\/\//, "")}/${c.database}`;
  return `${c.username}@${c.host}:${c.port}/${c.database}`;
}

function ConnectionFields({ kind, cfg, defaults, passwordSet, set }: {
  kind: Kind; cfg: Record<string, string | number>; defaults: Record<string, string | number>; passwordSet: boolean; set: (k: string, v: string) => void;
}) {
  const input = (k: string, label: string, type = "text") => (
    <Field label={label}>
      <input className="input" type={type} value={String(cfg[k] ?? "")} placeholder={k === "password" ? (passwordSet ? "•••••• (server default)" : "") : String(defaults[k] ?? "")}
        onChange={(e) => set(k, e.target.value)} autoComplete="off" />
    </Field>
  );
  if (kind === "postgresql" || kind === "mysql")
    return (
      <div className="grid grid-cols-2 gap-3">
        {input("host", "Host")}{input("port", "Port")}{input("database", "Database")}{input("username", "User")}
        <div className="col-span-2">{input("password", "Password", "password")}</div>
      </div>
    );
  if (kind === "mongodb") return <div className="grid gap-3">{input("uri", "Connection URI")}{input("database", "Database")}</div>;
  return (
    <div className="grid gap-3">
      <Field label="Database file" hint="Stored in the server's runtime/ folder; created if it doesn't exist.">
        <input className="input font-mono" value={String(cfg.file ?? "")} placeholder={String(defaults.file ?? "")} onChange={(e) => set("file", e.target.value)} />
      </Field>
    </div>
  );
}
