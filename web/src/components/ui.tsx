import { useState, type ReactNode } from "react";
import { AlertTriangle, Check, CheckCircle2, ChevronDown, Copy, Info, Loader2, XCircle } from "lucide-react";
import type { Table } from "../types";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function Card({ children, className, title, subtitle, action, icon }: {
  children: ReactNode; className?: string; title?: ReactNode; subtitle?: ReactNode; action?: ReactNode; icon?: ReactNode;
}) {
  return (
    <section className={cx("rounded-2xl border border-ink-700/80 bg-ink-850/80 backdrop-blur-sm", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 border-b border-ink-700/60 px-5 py-4">
          <div className="flex items-start gap-3">
            {icon && <div className="mt-0.5 text-accent">{icon}</div>}
            <div>
              <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
              {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
            </div>
          </div>
          {action}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";
export function Button({ children, onClick, variant = "secondary", loading, disabled, className, type = "button", title }: {
  children: ReactNode; onClick?: () => void; variant?: BtnVariant; loading?: boolean; disabled?: boolean; className?: string;
  type?: "button" | "submit"; title?: string;
}) {
  const styles: Record<BtnVariant, string> = {
    primary: "bg-accent text-ink-950 hover:bg-teal-300 shadow-glow font-semibold",
    secondary: "border border-ink-600 bg-ink-800 text-slate-200 hover:border-ink-600 hover:bg-ink-700",
    ghost: "text-slate-300 hover:bg-ink-800",
    danger: "border border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20",
  };
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled || loading}
      className={cx("inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-50", styles[variant], className)}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

type Tone = "neutral" | "good" | "bad" | "warn" | "accent" | "info";
const toneCls: Record<Tone, string> = {
  neutral: "border-ink-600 bg-ink-800 text-slate-300",
  good: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  bad: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  warn: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  accent: "border-accent/30 bg-accent-soft text-accent",
  info: "border-indigo-400/30 bg-indigo-500/10 text-indigo-300",
};

export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: Tone; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium", toneCls[tone], className)}>{children}</span>;
}

export function Alert({ tone = "info", title, children }: { tone?: Tone; title?: ReactNode; children?: ReactNode }) {
  const Icon = tone === "good" ? CheckCircle2 : tone === "bad" ? XCircle : tone === "warn" ? AlertTriangle : Info;
  return (
    <div className={cx("flex gap-3 rounded-xl border px-4 py-3 text-sm", toneCls[tone])}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 space-y-1 text-slate-200">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className="text-slate-300">{children}</div>}
      </div>
    </div>
  );
}

export function Metric({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "bad" | "accent" }) {
  return (
    <div className="rounded-xl border border-ink-700/80 bg-ink-900/70 px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">{label}</div>
      <div className={cx("mt-1 text-2xl font-semibold tabular-nums",
        tone === "good" ? "text-emerald-300" : tone === "bad" ? "text-rose-300" : tone === "accent" ? "text-accent" : "text-slate-100")}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="flex gap-1 overflow-x-auto rounded-xl border border-ink-700/80 bg-ink-900/60 p-1">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={cx("whitespace-nowrap rounded-lg px-3.5 py-1.5 text-sm transition",
            value === t.id ? "bg-ink-700 text-slate-100 shadow-sm" : "text-slate-400 hover:text-slate-200")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

function cell(v: unknown) {
  if (v === null || v === undefined || v === "") return <span className="text-slate-600">NULL</span>;
  if (typeof v === "boolean") return <span className={v ? "text-emerald-300" : "text-rose-300"}>{String(v)}</span>;
  if (typeof v === "object") return <span className="font-mono text-xs">{JSON.stringify(v)}</span>;
  return String(v);
}

export function DataTable({ data, maxHeight = 420, emptyText = "No rows", highlight }: {
  data?: Table | null; maxHeight?: number; emptyText?: string; highlight?: (col: string) => string | undefined;
}) {
  if (!data || !data.columns.length) return <EmptyState text={emptyText} />;
  return (
    <div className="overflow-auto rounded-xl border border-ink-700/80" style={{ maxHeight }}>
      <table className="min-w-full text-left text-sm">
        <thead className="sticky top-0 z-10 bg-ink-800/95 backdrop-blur">
          <tr>
            {data.columns.map((c) => (
              <th key={c} className={cx("whitespace-nowrap border-b border-ink-700 px-3 py-2 text-xs font-semibold text-slate-400", highlight?.(c))}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {data.rows.map((r, i) => (
            <tr key={i} className="hover:bg-ink-800/50">
              {r.map((v, j) => (
                <td key={j} className={cx("max-w-[420px] truncate whitespace-nowrap px-3 py-1.5 text-slate-300", highlight?.(data.columns[j]))} title={typeof v === "string" ? v : undefined}>
                  {cell(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!data.rows.length && <div className="p-4 text-center text-sm text-slate-500">{emptyText}</div>}
    </div>
  );
}

export function CodeBlock({ code, maxHeight = 360 }: { code: string; maxHeight?: number }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="group relative">
      <pre className="overflow-auto rounded-xl border border-ink-700/80 bg-ink-950/80 p-4 font-mono text-xs leading-relaxed text-slate-300" style={{ maxHeight }}>
        {code}
      </pre>
      <button onClick={() => { navigator.clipboard?.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
        className="absolute right-2 top-2 rounded-md border border-ink-600 bg-ink-800 p-1.5 text-slate-400 opacity-0 transition hover:text-slate-200 group-hover:opacity-100"
        title="Copy">
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

export function Collapsible({ title, children, defaultOpen = false, right }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean; right?: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-ink-700/80 bg-ink-900/40">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-sm text-slate-300 hover:text-slate-100">
        <span className="flex items-center gap-2">
          <ChevronDown className={cx("h-4 w-4 transition", !open && "-rotate-90")} />
          {title}
        </span>
        {right}
      </button>
      {open && <div className="border-t border-ink-700/60 p-4">{children}</div>}
    </div>
  );
}

export function EmptyState({ text, icon }: { text: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-ink-700 px-6 py-10 text-center text-sm text-slate-500">
      {icon}
      {text}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export function Segmented<T extends string>({ options, value, onChange }: { options: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-ink-600 bg-ink-900 p-0.5">
      {options.map((o) => (
        <button key={o.id} onClick={() => onChange(o.id)}
          className={cx("rounded-md px-3 py-1.5 text-sm transition", value === o.id ? "bg-accent text-ink-950 font-semibold" : "text-slate-400 hover:text-slate-200")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("shimmer rounded-lg", className)} />;
}

export function usePersistentState<T>(key: string, initial: T, storage: Storage = localStorage) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = storage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = (v: T | ((prev: T) => T)) => {
    setValue((prev) => {
      const next = typeof v === "function" ? (v as (p: T) => T)(prev) : v;
      try {
        storage.setItem(key, JSON.stringify(next));
      } catch {
        /* storage unavailable */
      }
      return next;
    });
  };
  return [value, set] as const;
}
