import { useEffect, useState } from "react";
import { ArrowLeftRight, Bot, History, Loader2, RefreshCw } from "lucide-react";
import { api } from "./api";
import { SystemGlyph } from "./components/EndpointPicker";
import { Alert, Button, cx } from "./components/ui";
import { AgentPage } from "./pages/AgentPage";
import { HistoryPage } from "./pages/HistoryPage";
import { MigratePage } from "./pages/MigratePage";
import type { AppConfig, Health, Kind } from "./types";

type Page = "migrate" | "agent" | "history";
const NAV: { id: Page; label: string; icon: typeof Bot }[] = [
  { id: "migrate", label: "Migrate", icon: ArrowLeftRight },
  { id: "agent", label: "AI Agent", icon: Bot },
  { id: "history", label: "History", icon: History },
];

function pageFromHash(): Page {
  const h = window.location.hash.replace("#/", "");
  return (["migrate", "agent", "history"] as Page[]).includes(h as Page) ? (h as Page) : "migrate";
}

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash());
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");

  const loadConfig = () => {
    setError("");
    api.config().then(setConfig).catch((e) => setError(e.message));
  };
  const loadHealth = () => api.health().then(setHealth).catch(() => setHealth(null));

  useEffect(() => {
    loadConfig();
    loadHealth();
    const t = setInterval(loadHealth, 30000);
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => { clearInterval(t); window.removeEventListener("hashchange", onHash); };
  }, []);

  const go = (p: Page) => { window.location.hash = `/${p}`; setPage(p); window.scrollTo({ top: 0 }); };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-ink-700/70 bg-ink-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3 sm:px-6">
          <a href="#/migrate" onClick={() => go("migrate")} className="flex items-center gap-2.5">
            <img src="/favicon.svg" className="h-8 w-8" alt="" />
            <div className="leading-tight">
              <div className="font-semibold text-slate-50">DataMigrate</div>
              <div className="text-[11px] text-slate-500">AI data migration agent</div>
            </div>
          </a>
          <nav className="flex gap-1">
            {NAV.map(({ id, label, icon: Icon }) => (
              <button key={id} onClick={() => go(id)}
                className={cx("flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition",
                  page === id ? "bg-ink-800 text-slate-50" : "text-slate-400 hover:text-slate-200")}>
                <Icon className="h-4 w-4" /><span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </nav>
          <div className="ml-auto hidden items-center gap-1.5 lg:flex">
            {health ? (
              <>
                {(["postgresql", "mysql", "mongodb", "duckdb", "sqlite"] as Kind[]).map((k) => (
                  <span key={k} title={health.systems[k]?.detail} className="relative">
                    <SystemGlyph kind={k} size="sm" />
                    <span className={cx("absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full ring-2 ring-ink-950", health.systems[k]?.ok ? "bg-emerald-400" : "bg-rose-500")} />
                  </span>
                ))}
                <span className="ml-2 flex items-center gap-1 rounded-md border border-ink-700 px-2 py-0.5 text-[11px] text-slate-400" title="LLM keys configured on the server">
                  <Bot className="h-3.5 w-3.5" />
                  {Object.entries(health.ai).filter(([, v]) => v).map(([k]) => k).join(", ") || "no AI key"}
                </span>
                <button onClick={loadHealth} className="ml-1 rounded p-1 text-slate-500 hover:text-slate-300" title="Refresh status"><RefreshCw className="h-3.5 w-3.5" /></button>
              </>
            ) : <Loader2 className="h-4 w-4 animate-spin text-slate-500" />}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        {error && (
          <div className="space-y-3">
            <Alert tone="bad" title="Cannot reach the API">{error}. Is the backend running? (<code>uvicorn api.main:app --port 8000</code>)</Alert>
            <Button onClick={loadConfig}><RefreshCw className="h-4 w-4" /> Retry</Button>
          </div>
        )}
        {!config && !error && <div className="flex justify-center py-24"><Loader2 className="h-6 w-6 animate-spin text-accent" /></div>}
        {config && page === "migrate" && <MigratePage config={config} />}
        {config && page === "agent" && <AgentPage config={config} />}
        {config && page === "history" && <HistoryPage config={config} />}
      </main>

      <footer className="mx-auto max-w-7xl px-6 pb-8 text-xs text-slate-600">
        PostgreSQL · MySQL · DuckDB · SQLite · MongoDB · LangGraph agent with human-in-the-loop review
      </footer>
    </div>
  );
}
