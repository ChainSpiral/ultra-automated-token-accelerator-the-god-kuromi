import { SiteHeader } from "@/components/SiteHeader";
import { FlowCanvas, type FlowNode, type FlowEdge } from "@/components/graph/FlowCanvas";

export const dynamic = "force-dynamic";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Meta = {
  seeds?: string[];
  from_block?: number;
  to_block?: number;
  cycle_nodes?: number;
};

export default async function FlowRoute({
  searchParams,
}: {
  searchParams: Promise<{ name?: string; view?: string }>;
}) {
  const sp = await searchParams;
  const view = sp.view === "full" ? "full" : "loop"; // 기본 = 루프만(읽기 쉽게)
  let nodes: FlowNode[] = [];
  let edges: FlowEdge[] = [];
  let meta: Meta = {};
  let error: string | null = null;
  let fullNodeCount = 0;
  try {
    const url = sp.name ? `${API}/api/flow?name=${sp.name}` : `${API}/api/flow`;
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`/api/flow → ${res.status}`);
    const raw = await res.json();
    nodes = raw.nodes ?? [];
    edges = raw.edges ?? [];
    meta = raw.metadata ?? {};
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  fullNodeCount = nodes.length;
  // loop 뷰: 사이클/seed 노드 + 거기에 닿는 mint/burn + Morpho 담보/차입 엣지. (DEX fan-out 노이즈 제거)
  if (view === "loop" && nodes.length) {
    const core = new Set(nodes.filter((n) => n.data.in_cycle || n.data.is_seed).map((n) => n.id));
    const keep = new Set(core);
    const ZERO = "0x0000000000000000000000000000000000000000";
    for (const e of edges) {
      if (core.has(e.source) && e.target === ZERO) keep.add(ZERO);
      if (core.has(e.target) && e.source === ZERO) keep.add(ZERO);
      // Morpho 담보/차입은 core 와 닿으면 Morpho 노드+상대까지 유지
      if (e.morpho && (core.has(e.source) || core.has(e.target))) {
        keep.add(e.source); keep.add(e.target);
      }
    }
    nodes = nodes.filter((n) => keep.has(n.id));
    edges = edges.filter((e) => keep.has(e.source) && keep.has(e.target));
  }

  const cycleEdges = edges.filter((e) => e.in_cycle).length;

  return (
    <div className="flex h-dvh flex-col">
      <SiteHeader />
      {!error && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-5 py-2 font-mono text-[11px] text-[var(--color-text-muted)]">
          <span className="font-semibold text-[var(--color-text-secondary)]">VALUE FLOW</span>
          {meta.from_block != null && (
            <span>
              block{" "}
              <span className="text-[var(--color-text-primary)]">
                {meta.from_block.toLocaleString()}–{meta.to_block?.toLocaleString()}
              </span>
            </span>
          )}
          <span>·</span>
          <span>
            nodes <span className="text-[var(--color-text-secondary)]">{nodes.length}</span> / edges{" "}
            <span className="text-[var(--color-text-secondary)]">{edges.length}</span>
          </span>
          {cycleEdges > 0 && (
            <span className="rounded bg-[#ef4444]/15 px-1.5 py-0.5 font-semibold text-[#f87171]">
              ⟳ 순환(self-minting loop) 엣지 {cycleEdges}개 감지
            </span>
          )}
          <span className="flex items-center gap-0.5 rounded-md border border-[var(--color-border-subtle)] p-0.5">
            <a
              href={`/flow?name=${sp.name ?? "stream"}&view=loop`}
              className={view === "loop" ? "rounded bg-[var(--color-accent)] px-1.5 py-0.5 text-white" : "px-1.5 py-0.5"}
            >
              루프만
            </a>
            <a
              href={`/flow?name=${sp.name ?? "stream"}&view=full`}
              className={view === "full" ? "rounded bg-[var(--color-accent)] px-1.5 py-0.5 text-white" : "px-1.5 py-0.5"}
            >
              전체 {fullNodeCount}
            </a>
          </span>
          {/* legend */}
          <span className="ml-auto flex items-center gap-3 text-[10px]">
            <Dot c="#fbbf24" t="seed" />
            <Dot c="#ef4444" t="cycle" />
            <Dot c="#eab308" t="Morpho 담보/차입" />
            <Dot c="#334155" t="EOA" />
            <Dot c="#1d4ed8" t="contract" />
            <Dot c="#7f1d1d" t="mint/burn" />
          </span>
        </div>
      )}
      {error ? (
        <div className="flex flex-1 items-center justify-center p-12 text-center">
          <div className="space-y-2">
            <h2 className="text-lg font-semibold text-[var(--color-danger)]">플로우를 불러오지 못했습니다</h2>
            <p className="text-sm text-[var(--color-text-muted)]">{error}</p>
            <p className="text-xs text-[var(--color-text-muted)]">
              생성: python3 feeder/flow_trace.py --seeds … --from … --to … --out graphs/frontend/flow.stream.json
            </p>
          </div>
        </div>
      ) : (
        <FlowCanvas nodes={nodes} edges={edges} />
      )}
    </div>
  );
}

function Dot({ c, t }: { c: string; t: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="inline-block size-2 rounded-full" style={{ backgroundColor: c }} />
      {t}
    </span>
  );
}
