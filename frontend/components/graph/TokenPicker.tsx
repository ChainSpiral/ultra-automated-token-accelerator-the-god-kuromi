"use client";

import { useRouter } from "next/navigation";

type Tok = {
  symbol: string;
  nodes: number;
  edges: number;
  block: number;
  avg_coverage?: number | null;
};

function fmtCov(v: number | null | undefined): string {
  return typeof v === "number" ? `${(v * 100).toFixed(0)}%` : "-";
}

export function TokenPicker({ tokens, selected }: { tokens: Tok[]; selected?: string }) {
  const router = useRouter();
  return (
    <div className="flex items-center gap-3 border-b border-white/10 bg-[#0b1220] px-4 py-2 text-sm">
      <span className="text-[var(--color-text-muted)]">토큰</span>
      <select
        value={selected ?? ""}
        onChange={(e) => router.push(`/overview?token=${e.target.value}`)}
        className="rounded-md border border-white/15 bg-[#111c33] px-2 py-1 text-gray-100"
      >
        {tokens.map((t) => (
          <option key={t.symbol} value={t.symbol}>
            {t.symbol}  ({t.nodes}n/{t.edges}e · cov {fmtCov(t.avg_coverage)})
          </option>
        ))}
      </select>
      <span className="text-xs text-[var(--color-text-muted)]">
        {tokens.length} tokens · block {tokens[0]?.block ?? "-"}
      </span>
    </div>
  );
}
