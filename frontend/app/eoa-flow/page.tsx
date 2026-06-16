import { SiteHeader } from "@/components/SiteHeader";
import { EoaFlowCanvas, type EoaFlowEdge, type EoaFlowNode } from "@/components/graph/EoaFlowCanvas";

export const dynamic = "force-dynamic";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type EoaFlowItem = {
  name: string;
  label: string;
  nodes: number;
  edges: number;
  events: number;
  addresses: number;
};

type EoaFlowMeta = {
  view?: string;
  address_count?: number;
  event_count?: number;
  from_block?: number;
  to_block?: number;
  generated_at_utc?: string;
  category_counts?: Record<string, number>;
  max_events_per_address?: number;
};

export default async function EoaFlowRoute({
  searchParams,
}: {
  searchParams: Promise<{ name?: string; address?: string; depth?: string }>;
}) {
  const sp = await searchParams;

  let flowList: EoaFlowItem[] = [];
  try {
    const r = await fetch(`${API}/api/eoa-flows`, { cache: "no-store" });
    if (r.ok) flowList = await r.json();
  } catch {
    /* render the error state below */
  }

  const active = sp.name ?? flowList[0]?.name ?? "weETH";
  const seedAddress = sp.address?.trim();
  const depth = sp.depth && /^\d+$/.test(sp.depth) ? sp.depth : "1";

  let nodes: EoaFlowNode[] = [];
  let edges: EoaFlowEdge[] = [];
  let meta: EoaFlowMeta = {};
  let error: string | null = null;
  try {
    const query = seedAddress
      ? `address=${encodeURIComponent(seedAddress)}&depth=${encodeURIComponent(depth)}`
      : `name=${encodeURIComponent(active)}`;
    const res = await fetch(`${API}/api/eoa-flow?${query}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`/api/eoa-flow -> ${res.status}`);
    const raw = await res.json();
    nodes = raw.nodes ?? [];
    edges = raw.edges ?? [];
    meta = raw.metadata ?? {};
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const categoryCounts = meta.category_counts ?? {};

  return (
    <div className="flex h-dvh flex-col">
      <SiteHeader />
      {flowList.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-5 py-2 text-[11px]">
          <span className="mr-1 font-mono font-semibold text-[var(--color-text-muted)]">EOA FLOW</span>
          {flowList.map((f) => {
            const on = !seedAddress && f.name === active;
            return (
              <a
                key={f.name}
                href={`/eoa-flow?name=${f.name}`}
                title={`${f.addresses} addresses · ${f.events} events`}
                className={`flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono transition-colors ${
                  on
                    ? "border-[var(--color-accent)] bg-[var(--color-accent)] text-white"
                    : "border-[var(--color-border-subtle)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]"
                }`}
              >
                {f.label}
                <span className={on ? "text-white/75" : "text-[var(--color-text-muted)]"}>{f.events}</span>
              </a>
            );
          })}
          <form action="/eoa-flow" className="ml-auto flex min-w-[420px] items-center gap-1.5">
            <input
              name="address"
              defaultValue={seedAddress ?? ""}
              placeholder="0x seed address"
              className="h-7 min-w-0 flex-1 rounded-md border border-[var(--color-border-subtle)] bg-[#0b1220] px-2 font-mono text-[11px] text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
            />
            <select
              name="depth"
              defaultValue={depth}
              className="h-7 rounded-md border border-[var(--color-border-subtle)] bg-[#0b1220] px-2 font-mono text-[11px] text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
            >
              <option value="0">d0</option>
              <option value="1">d1</option>
              <option value="2">d2</option>
            </select>
            <button
              type="submit"
              className="h-7 rounded-md border border-[var(--color-accent)] bg-[var(--color-accent)] px-3 font-mono text-[11px] font-semibold text-white"
            >
              trace
            </button>
          </form>
        </div>
      )}

      {!error && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-5 py-2 font-mono text-[11px] text-[var(--color-text-muted)]">
          <span className="font-semibold text-[var(--color-text-secondary)]">EOA SEMANTIC FLOW</span>
          <span>
            addresses <span className="text-[var(--color-text-secondary)]">{meta.address_count ?? 0}</span>
          </span>
          <span>
            events <span className="text-[var(--color-text-secondary)]">{meta.event_count ?? edges.length}</span>
          </span>
          <span>
            nodes <span className="text-[var(--color-text-secondary)]">{nodes.length}</span> / edges{" "}
            <span className="text-[var(--color-text-secondary)]">{edges.length}</span>
          </span>
          {meta.from_block != null && (
            <span>
              block{" "}
              <span className="text-[var(--color-text-secondary)]">
                {meta.from_block.toLocaleString()}-{meta.to_block?.toLocaleString()}
              </span>
            </span>
          )}
          {Object.keys(categoryCounts).length > 0 && (
            <span className="ml-auto flex flex-wrap gap-1 text-[10px]">
              {Object.entries(categoryCounts).map(([k, v]) => (
                <span key={k} className="rounded-md border border-[var(--color-border-subtle)] px-1.5 py-0.5">
                  {k} {v}
                </span>
              ))}
            </span>
          )}
        </div>
      )}

      {error ? (
        <div className="flex flex-1 items-center justify-center p-12 text-center">
          <div className="space-y-2">
            <h2 className="text-lg font-semibold text-[var(--color-danger)]">EOA flow를 불러오지 못했습니다</h2>
            <p className="text-sm text-[var(--color-text-muted)]">{error}</p>
            <p className="font-mono text-xs text-[var(--color-text-muted)]">
              python3 feeder/eoa_timeline.py --graph graphs/frontend/weETH.sim.json --important-only --frontend-flow --out graphs/frontend/eoa.weETH.json
            </p>
          </div>
        </div>
      ) : (
        <EoaFlowCanvas nodes={nodes} edges={edges} />
      )}
    </div>
  );
}
