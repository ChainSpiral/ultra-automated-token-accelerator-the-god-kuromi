import { SiteHeader } from "@/components/SiteHeader";

export const dynamic = "force-dynamic";
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Tok = {
  grade: string; token: string; cycle: boolean; oracle_class: string; sees?: string;
  distressed?: boolean; backing?: string; loan?: string; collat_usd?: number;
  oracle?: string; oracle_name?: string; n_markets?: number;
  concentration?: number | null; n_borrowers?: number; borrow_usd?: number;
  sole_borrower?: boolean; looping?: boolean;
};

const GRADE_COLOR: Record<string, string> = {
  CRITICAL: "#ef4444", DISTRESSED: "#fb923c", HIGH: "#f59e0b",
  MED: "#eab308", CHECK: "#64748b", ok: "#22c55e",
};
const GRADE_DESC: Record<string, string> = {
  CRITICAL: "순환백킹 또는 private시장+reflexive 오라클",
  DISTRESSED: "담보 가격불가+큰부채 = 이미 frozen/bad-debt",
  HIGH: "합성 전용/NAV 오라클(reflexive) 또는 sole-borrower",
  MED: "자기 NAV(convertToAssets), peg 가정",
  CHECK: "비표준 오라클 — 수동확인",
  ok: "실물 앵커 또는 시장피드 — 정상",
};

function usd(n?: number) {
  if (!n) return "$0";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export default async function ReflexivityRoute() {
  let block: number | undefined;
  let order: string[] = ["CRITICAL", "DISTRESSED", "HIGH", "MED", "CHECK", "ok"];
  let rows: [string, Tok][] = [];
  let error: string | null = null;
  try {
    const res = await fetch(`${API}/api/reflexivity`, { cache: "no-store" });
    if (!res.ok) throw new Error(`/api/reflexivity → ${res.status}`);
    const d = await res.json();
    block = d.block;
    order = d.order ?? order;
    rows = Object.entries(d.tokens ?? {}) as [string, Tok][];
    const rank = (g: string) => { const i = order.indexOf(g); return i < 0 ? 99 : i; };
    rows.sort((a, b) => rank(a[1].grade) - rank(b[1].grade) || a[0].localeCompare(b[0]));
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const counts: Record<string, number> = {};
  for (const [, t] of rows) counts[t.grade] = (counts[t.grade] ?? 0) + 1;

  return (
    <div className="flex h-dvh flex-col">
      <SiteHeader />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-5 py-2 font-mono text-[11px] text-[var(--color-text-muted)]">
        <span className="font-semibold text-[var(--color-text-secondary)]">REFLEXIVITY SCAN</span>
        {block && <span>block <span className="text-[var(--color-text-primary)]">{block.toLocaleString()}</span></span>
        }
        <span>· {rows.length} tokens</span>
        <span className="ml-auto flex items-center gap-3">
          {order.filter((g) => counts[g]).map((g) => (
            <span key={g} className="flex items-center gap-1">
              <span className="inline-block size-2 rounded-full" style={{ background: GRADE_COLOR[g] }} />
              {g} {counts[g]}
            </span>
          ))}
        </span>
      </div>
      {error ? (
        <div className="flex flex-1 items-center justify-center p-12 text-center text-sm text-[var(--color-text-muted)]">
          <div>
            <p className="text-[var(--color-danger)]">reflexivity 데이터를 불러오지 못했습니다: {error}</p>
            <p className="mt-2 text-xs">생성: python3 feeder/reflexivity_scan.py [--auto N]</p>
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-auto p-4">
          <table className="w-full border-collapse text-[12px]">
            <thead className="sticky top-0 bg-[var(--color-surface)]">
              <tr className="text-left text-[var(--color-text-muted)]">
                <th className="px-2 py-1.5">등급</th>
                <th className="px-2 py-1.5">토큰</th>
                <th className="px-2 py-1.5">담보→차입</th>
                <th className="px-2 py-1.5">오라클</th>
                <th className="px-2 py-1.5">오라클이 보는 것</th>
                <th className="px-2 py-1.5">집중도</th>
                <th className="px-2 py-1.5">백킹 의존</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([sym, t]) => (
                <tr key={sym} className="border-t border-[var(--color-border-subtle)] align-top hover:bg-[var(--color-surface-raised)]">
                  <td className="px-2 py-1.5">
                    <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-black" style={{ background: GRADE_COLOR[t.grade] ?? "#888" }}>
                      {t.grade}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 font-mono font-medium text-[var(--color-text-primary)]">
                    {sym}{t.distressed ? " ⚠FROZEN" : ""}{t.cycle ? " ⟳" : ""}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[var(--color-text-secondary)]">
                    {t.loan ? `→${t.loan} (${usd(t.collat_usd)})` : "—"}
                  </td>
                  <td className="px-2 py-1.5">
                    <span className="font-mono text-[11px]" style={{ color: ["bespoke/NAV", "self-NAV"].includes(t.oracle_class) ? "#f59e0b" : "var(--color-text-muted)" }}>
                      {t.oracle_class}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[10px] text-[var(--color-text-muted)]">{t.sees || "—"}</td>
                  <td className="px-2 py-1.5 font-mono text-[11px]">
                    {t.n_borrowers ? (
                      <span style={{ color: t.sole_borrower ? "#ef4444" : "var(--color-text-muted)" }}>
                        {Math.round((t.concentration ?? 0) * 100)}% / {t.n_borrowers}명{t.sole_borrower ? " ★sole" : ""}
                      </span>
                    ) : "—"}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[10px] text-[var(--color-text-muted)]">{t.backing && t.backing !== "-" ? t.backing : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-4 space-y-0.5 px-2 text-[10px] text-[var(--color-text-muted)]">
            {order.map((g) => (
              <div key={g}>
                <span className="font-semibold" style={{ color: GRADE_COLOR[g] }}>{g}</span>: {GRADE_DESC[g]}
              </div>
            ))}
            <div className="pt-1 italic">⟳ = 순환백킹 · ⚠FROZEN = 담보 가격불가(이미 bad-debt 가능) · ★sole = 단일 차입자 private 시장</div>
          </div>
        </div>
      )}
    </div>
  );
}
