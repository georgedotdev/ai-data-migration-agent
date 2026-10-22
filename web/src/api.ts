import type { AgentView, AppConfig, EndpointSpec, Health, MigrationResult, Table } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON */
  }
  if (!res.ok) {
    const detail = body?.detail;
    throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: any) => d.msg).join("; ") : `Request failed (${res.status})`);
  }
  return body as T;
}

const post = <T,>(path: string, data: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(data) });

export const api = {
  config: () => request<AppConfig>("/api/config"),
  health: () => request<Health>("/api/health"),
  test: (spec: EndpointSpec, role: "source" | "target") => post<{ ok: boolean; message: string }>(`/api/test?role=${role}`, spec),
  tables: (spec: EndpointSpec, role: "source" | "target") => post<{ tables: string[]; error?: string }>(`/api/tables?role=${role}`, spec),
  seed: (endpoint: EndpointSpec, tables?: string[]) => post<{ seeded: Record<string, number> }>("/api/seed", { endpoint, tables }),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ upload_id: string; filename: string; columns: string[]; preview: Table }>("/api/upload", { method: "POST", body: fd });
  },
  migrate: (body: { source: EndpointSpec; target: EndpointSpec; normalize_column?: string | null; lookup_table?: string | null }) =>
    post<MigrationResult>("/api/migrate", body),
  query: (rid: string, name: string) => post<Table>(`/api/migrations/${rid}/query`, { name }),
  exportUrl: (rid: string) => `/api/migrations/${rid}/export.csv`,
  history: (spec: EndpointSpec) => post<Table & { error?: string }>("/api/history", spec),
  agentStart: (body: { source: EndpointSpec; target: EndpointSpec; provider: string; model: string; goal: string; api_keys: Record<string, string> }) =>
    post<AgentView>("/api/agent/start", body),
  agentResume: (tid: string, body: { approved: boolean; feedback: string; rejected_steps: number[]; api_keys: Record<string, string> }) =>
    post<AgentView>(`/api/agent/${tid}/resume`, body),
  agentDbUrl: (tid: string) => `/api/agent/${tid}/database`,
};
