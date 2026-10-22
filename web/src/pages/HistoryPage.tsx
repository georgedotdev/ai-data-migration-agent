import { useState } from "react";
import { History, Search } from "lucide-react";
import { api } from "../api";
import { EndpointPicker } from "../components/EndpointPicker";
import type { AppConfig, EndpointSpec, Table } from "../types";
import { Alert, Button, Card, DataTable, usePersistentState } from "../components/ui";

export function HistoryPage({ config }: { config: AppConfig }) {
  const [target, setTarget] = usePersistentState<EndpointSpec>("hi.target", { kind: "mysql", config: {}, table: "" });
  const [data, setData] = useState<Table | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.history(target);
      if (r.error) setErr(r.error);
      setData(r);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-50"><History className="h-6 w-6 text-accent" /> Run history</h1>
        <p className="mt-1 text-sm text-slate-400">Every migration is recorded in the target's own <code>migration_runs</code> table (a collection in MongoDB), with a CHECK constraint that the row accounting balances.</p>
      </div>
      <Card title="Target system">
        <EndpointPicker role="target" systems={config.systems} value={target} onChange={setTarget} />
        <div className="mt-4"><Button variant="primary" onClick={load} loading={busy}><Search className="h-4 w-4" /> Load history</Button></div>
      </Card>
      {err && <Alert tone="warn">{err}</Alert>}
      {data && !err && <Card title={`${data.rows.length} runs`}><DataTable data={data} maxHeight={600} /></Card>}
    </div>
  );
}
