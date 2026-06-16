import { SiteHeader } from "@/components/SiteHeader";
import { OverviewCanvas } from "@/components/graph/OverviewCanvas";
import { TokenPicker } from "@/components/graph/TokenPicker";

export const dynamic = "force-dynamic";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type RawNode = { id: string; type: string; label: string; data?: Record<string, unknown> };
type RawEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  edge_type?: string;
  coverage?: number;
};
type Tok = {
  symbol: string;
  nodes: number;
  edges: number;
  block: number;
  file: string;
  avg_coverage?: number | null;
};

function nodeKind(n: RawNode): string {
  return String(n.data?.category ?? n.data?.kind ?? n.type);
}

function isVisibleGraphNode(n: RawNode): boolean {
  return n.type !== "bridge" && nodeKind(n) !== "EOA";
}

export default async function OverviewRoute({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const sp = await searchParams;
  let tokens: Tok[] = [];
  try {
    const m = await (await fetch(`${API}/api/manifest`, { cache: "no-store" })).json();
    tokens = m.tokens ?? [];
  } catch {
    /* manifest 없으면 기본 그래프로 */
  }
  const selected = sp.token ?? tokens[0]?.symbol;
  const tokenMeta = tokens.find((t) => t.symbol === selected);

  let nodes: RawNode[] = [];
  let edges: RawEdge[] = [];
  let error: string | null = null;
  try {
    const url = selected ? `${API}/api/graph?token=${selected}` : `${API}/api/graph`;
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`/api/graph → ${res.status}`);
    const raw = await res.json();
    nodes = (raw.nodes ?? []).filter((n: RawNode) => n.type !== "bridge");
    const keep = new Set(nodes.map((n) => n.id));
    edges = (raw.edges ?? []).filter((e: RawEdge) => keep.has(e.source) && keep.has(e.target));
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const visibleNodeIds = new Set(nodes.filter(isVisibleGraphNode).map((n) => n.id));
  const visibleNodeCount = visibleNodeIds.size;
  const visibleEdgeCount = edges.filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)).length;
  const covs = edges
    .filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target))
    .map((e) => e.coverage)
    .filter((c): c is number => typeof c === "number");
  const avgCov =
    typeof tokenMeta?.avg_coverage === "number"
      ? tokenMeta.avg_coverage
      : covs.length
        ? covs.reduce((a, b) => a + b, 0) / covs.length
        : null;

  return (
    <div className="flex h-dvh flex-col">
      <SiteHeader />
      {tokens.length > 0 && <TokenPicker tokens={tokens} selected={selected} />}
      {!error && tokenMeta && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-5 py-2 font-mono text-[11px] text-[var(--color-text-muted)]">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block size-1.5 rounded-full bg-[var(--color-healthy)]" />
            <span className="text-[var(--color-text-secondary)]">스냅샷</span> block{" "}
            <span className="text-[var(--color-text-primary)]">{tokenMeta.block.toLocaleString()}</span>
          </span>
          <span>·</span>
          <span>
            nodes <span className="text-[var(--color-text-secondary)]">{visibleNodeCount}</span> / edges{" "}
            <span className="text-[var(--color-text-secondary)]">{visibleEdgeCount}</span>
          </span>
          {avgCov != null && (
            <>
              <span>·</span>
              <span>
                평균 coverage{" "}
                <span className="text-[var(--color-text-secondary)]">{(avgCov * 100).toFixed(0)}%</span>
              </span>
            </>
          )}
          <span className="ml-auto text-[10px]">같은 block 재실행 시 동일 그래프 (재현 가능)</span>
        </div>
      )}
      {error ? (
        <div className="flex flex-1 items-center justify-center p-12 text-center">
          <div className="space-y-2">
            <h2 className="text-lg font-semibold text-[var(--color-danger)]">그래프를 불러오지 못했습니다</h2>
            <p className="text-sm text-[var(--color-text-muted)]">{error}</p>
            <p className="text-xs text-[var(--color-text-muted)]">mock 서버(:8000) 실행 확인: python3 mock_server.py</p>
          </div>
        </div>
      ) : (
        <OverviewCanvas nodes={nodes} edges={edges} />
      )}
    </div>
  );
}
