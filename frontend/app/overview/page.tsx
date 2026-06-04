import { SiteHeader } from "@/components/SiteHeader";
import { OverviewCanvas } from "@/components/graph/OverviewCanvas";
import { TokenPicker } from "@/components/graph/TokenPicker";

export const dynamic = "force-dynamic";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type RawNode = { id: string; type: string; label: string; data?: Record<string, unknown> };
type RawEdge = { id: string; source: string; target: string; label?: string; edge_type?: string };
type Tok = { symbol: string; nodes: number; edges: number; block: number; file: string };

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

  return (
    <div className="flex h-dvh flex-col">
      <SiteHeader />
      {tokens.length > 0 && <TokenPicker tokens={tokens} selected={selected} />}
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
