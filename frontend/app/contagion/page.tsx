import { SiteHeader } from "@/components/SiteHeader";
import { ContagionCanvas, type CNode, type CEdge } from "@/components/graph/ContagionCanvas";

export const dynamic = "force-dynamic";
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type IndexItem = {
  address: string;
  name: string;
  asset: string;
  tvl_usd: number;
  n_markets: number;
  n_collaterals: number;
  top_shared_collat: string | null;
  top_shared_pct: number;
  top_issuer: string | null;
  top_issuer_pct: number;
  n_issuers: number;
  n_shared_oracle: number;
  worst_collat_grade: string | null;
};
type Score = {
  n_markets: number;
  n_collaterals: number;
  n_shared_collat: number;
  n_shared_oracle: number;
  n_issuers: number;
  top_shared_collat: string | null;
  top_shared_pct: number;
  top_issuer: string | null;
  top_issuer_pct: number;
  worst_collat_grade: string | null;
};

const GRADE_COLOR: Record<string, string> = {
  CRITICAL: "#ef4444", DISTRESSED: "#fb923c", HIGH: "#f59e0b",
  MED: "#eab308", CHECK: "#64748b", ok: "#22c55e",
};

function fmtM(n?: number) {
  if (!n) return "$0";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export default async function ContagionRoute({
  searchParams,
}: {
  searchParams: Promise<{ vault?: string }>;
}) {
  const sp = await searchParams;

  let index: IndexItem[] = [];
  try {
    const r = await fetch(`${API}/api/contagions`, { cache: "no-store" });
    if (r.ok) index = (await r.json()).vaults ?? [];
  } catch {
    /* selector 숨김 */
  }
  const active = sp.vault ?? index[0]?.address;

  let nodes: CNode[] = [];
  let edges: CEdge[] = [];
  let vault: { name: string; asset: string; tvl_usd: number; address: string } | null = null;
  let score: Score | null = null;
  let error: string | null = null;
  try {
    const url = active ? `${API}/api/contagion?vault=${active}` : `${API}/api/contagion`;
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`/api/contagion → ${res.status}`);
    const d = await res.json();
    nodes = d.nodes ?? [];
    edges = d.edges ?? [];
    vault = d.vault ?? null;
    score = d.score ?? null;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const issuerPct = score?.top_issuer_pct ?? 0;
  const collatPct = score?.top_shared_pct ?? 0;
  // 발행자 수렴이 담보 집중보다 크거나 같으면 그게 진짜(더 무서운) 헤드라인.
  const issuerLeads = issuerPct >= collatPct && !!score?.top_issuer;
  const danger = Math.max(issuerPct, collatPct) >= 0.5;

  return (
    <div className="flex h-dvh flex-col">
      <SiteHeader />

      {/* 볼트 셀렉터 (위험순) */}
      {index.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-5 py-2 text-[11px]">
          <span className="mr-1 font-mono font-semibold text-[var(--color-text-muted)]">볼트</span>
          {index.map((v) => {
            const on = v.address === active;
            const hPct = Math.max(v.top_issuer_pct ?? 0, v.top_shared_pct ?? 0);
            const hLabel = (v.top_issuer_pct ?? 0) >= (v.top_shared_pct ?? 0) ? v.top_issuer : v.top_shared_collat;
            const vdanger = hPct >= 0.5;
            return (
              <a
                key={v.address}
                href={`/contagion?vault=${v.address}`}
                title={`${v.n_markets}마켓 / ${v.n_collaterals}담보 / ${v.n_issuers}발행자 · ${fmtM(v.tvl_usd)}${hLabel ? ` · ${hLabel} ${Math.round(hPct * 100)}%` : ""}`}
                className={`flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono transition-colors ${
                  on
                    ? "border-[var(--color-accent)] bg-[var(--color-accent)] text-white"
                    : "border-[var(--color-border-subtle)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]"
                }`}
              >
                {v.name}
                {vdanger && (
                  <span className={on ? "text-white" : "text-[#f87171]"}>
                    {Math.round(hPct * 100)}%
                  </span>
                )}
              </a>
            );
          })}
        </div>
      )}

      {/* 요약 + 동시청산 배너 */}
      {!error && vault && score && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-5 py-2 font-mono text-[11px] text-[var(--color-text-muted)]">
          <span className="font-semibold text-[var(--color-text-secondary)]">CONTAGION</span>
          <span>
            <span className="text-[var(--color-text-primary)]">{vault.name}</span> ({vault.asset}) · TVL{" "}
            {fmtM(vault.tvl_usd)}
          </span>
          <span>·</span>
          <span>
            {score.n_markets}마켓 → {score.n_collaterals}담보 → {score.n_issuers}발행자
          </span>
          {score.top_issuer && (
            <span
              className={`rounded px-1.5 py-0.5 font-semibold ${
                issuerPct >= 0.5 ? "bg-[#ef4444]/20 text-[#f87171]" : "bg-[#eab308]/15 text-[#fde047]"
              }`}
            >
              {issuerPct >= 0.5 ? "⚠ 발행자 수렴" : "발행자"}: {score.top_issuer} {Math.round(issuerPct * 100)}%
            </span>
          )}
          {score.top_shared_collat && (
            <span className="rounded bg-[#eab308]/10 px-1.5 py-0.5 text-[#fde047]">
              공유담보: {score.top_shared_collat} {Math.round(collatPct * 100)}%
            </span>
          )}
          {score.n_shared_oracle > 0 && (
            <span className="rounded bg-[#a78bfa]/15 px-1.5 py-0.5 text-[#c4b5fd]">
              공유오라클 {score.n_shared_oracle}
            </span>
          )}
          {/* legend */}
          <span className="ml-auto flex items-center gap-2 text-[10px]">
            {(["CRITICAL", "HIGH", "MED", "ok"] as const).map((g) => (
              <span key={g} className="flex items-center gap-1">
                <span className="inline-block size-2 rounded-full" style={{ background: GRADE_COLOR[g] }} />
                {g}
              </span>
            ))}
            <span className="flex items-center gap-1">
              <span className="inline-block size-2 rounded-full" style={{ background: "#475569" }} />
              unscanned
            </span>
          </span>
        </div>
      )}

      {/* 한 줄 인사이트 — 발행자 수렴이 헤드라인이면 그걸 리드 */}
      {!error && danger && score && (
        <div className="border-b border-[var(--color-border-subtle)] bg-[#ef4444]/10 px-5 py-1.5 text-[11px] text-[#fca5a5]">
          {issuerLeads && score.top_issuer ? (
            <>
              이 볼트는 {score.n_markets}개 마켓 / {score.n_collaterals}개 담보로 분산된 것처럼 보이지만, 실제
              익스포저의 <b>{Math.round(issuerPct * 100)}%가 {score.top_issuer} 단일 발행자</b>로 귀결됩니다 —{" "}
              {score.top_issuer}계열 자산이 함께 흔들리면 이 마켓들이 <b>동시에</b> 청산될 수 있습니다. (서로 달라
              보이는 담보들이 한 발행자로 수렴 = 표로는 안 보이고 그래프로만 드러나는 2차 리스크. 발행자 귀속은
              heuristic)
            </>
          ) : score.top_shared_collat ? (
            <>
              이 볼트는 {score.n_markets}개 마켓에 분산된 것처럼 보이지만, 실제 익스포저의{" "}
              <b>{Math.round(collatPct * 100)}%가 {score.top_shared_collat} 단일 담보</b>로 수렴합니다 —{" "}
              {score.top_shared_collat} 한 번의 디페그가 이 마켓들을 <b>동시에</b> 청산시킬 수 있습니다.
              (Reflexivity·Flow로는 보이지 않는 포트폴리오 2차 리스크)
            </>
          ) : null}
        </div>
      )}

      {error ? (
        <div className="flex flex-1 items-center justify-center p-12 text-center">
          <div className="space-y-2">
            <h2 className="text-lg font-semibold text-[var(--color-danger)]">contagion 데이터를 불러오지 못했습니다</h2>
            <p className="text-sm text-[var(--color-text-muted)]">{error}</p>
            <p className="text-xs text-[var(--color-text-muted)]">생성: python3 feeder/contagion.py --top 15</p>
          </div>
        </div>
      ) : (
        <ContagionCanvas nodes={nodes} edges={edges} />
      )}
    </div>
  );
}
