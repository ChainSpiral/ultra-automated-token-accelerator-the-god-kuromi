"use client";

import { useMemo, useState } from "react";
import type { ShockableAsset } from "@/lib/api";

export interface ContagionControls {
  asset: string;
  delta: number;
  channel: "depeg" | "liquidity";
  /** depeg only: show the M1 absorption floor (no amplification) */
  naive: boolean;
  /** inject event-discovered hidden cross-protocol dependencies (shared-whale bridges) */
  includeDiscovered: boolean;
  /** auto-derive liquidation recovery per asset (NAV ~98% / DEX ~95% + fire-sale); else manual r */
  recoveryAuto: boolean;
  morpho: boolean;
  aave: boolean;
  spark: boolean;
  skycdp: boolean;
  recovery: number;
  downstream: boolean;
  /** csv of collateral symbols to freeze (governance blocker) */
  freeze: string;
}

interface Props {
  assets: ShockableAsset[];
  controls: ContagionControls;
  onChange: (patch: Partial<ContagionControls>) => void;
  running: boolean;
  onRun: () => void;
  /** search target: collateral tokens vs shared oracles (separate lists) */
  searchKind: "token" | "oracle";
  onSearchKindChange: (k: "token" | "oracle") => void;
}

function fmtUsd(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

function Section({ tag, title, children }: { tag: string; title: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-[var(--color-border-subtle)] px-5 py-4">
      <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-accent)]">{tag}</p>
      <p className="mb-3 text-[11px] text-[var(--color-text-muted)]">{title}</p>
      {children}
    </div>
  );
}

function VenueBadge({ venues }: { venues?: string[] }) {
  if (!venues) return null;
  return (
    <span className="ml-1 inline-flex gap-0.5">
      {venues.includes("oracle") && <span className="rounded bg-[rgba(251,191,36,0.18)] px-1 text-[8px] font-bold text-[#fbbf24]">O</span>}
      {venues.includes("morpho") && <span className="rounded bg-[rgba(124,131,255,0.16)] px-1 text-[8px] font-bold text-[#aab0ff]">M</span>}
      {venues.includes("aave") && <span className="rounded bg-[rgba(52,211,153,0.16)] px-1 text-[8px] font-bold text-[#34d399]">A</span>}
    </span>
  );
}

export function ContagionControlPanel({ assets, controls, onChange, running, onRun, searchKind, onSearchKindChange }: Props) {
  const c = controls;
  const isOracle = searchKind === "oracle";
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = (a: ShockableAsset) =>
      a.symbol.toLowerCase().includes(q) ||
      (a.label?.toLowerCase().includes(q) ?? false) ||
      (a.affected?.some((s) => s.toLowerCase().includes(q)) ?? false);
    const list = q ? assets.filter(match) : assets;
    return list.slice(0, 40);
  }, [assets, query]);
  const selected = useMemo(() => assets.find((a) => a.symbol === c.asset), [assets, c.asset]);
  // oracle targets carry their id in `symbol`; show the human label instead.
  const selectedDisplay = selected?.kind === "oracle" ? (selected.label ?? c.asset) : c.asset;
  return (
    <aside className="flex w-[300px] shrink-0 flex-col overflow-y-auto border-r border-[var(--color-border-subtle)] bg-[var(--color-surface)]">
      <div className="border-b border-[var(--color-border-subtle)] px-5 py-4">
        <h2 className="text-base font-bold text-[var(--color-text-primary)]">전염 시뮬레이션</h2>
        <p className="text-[11px] text-[var(--color-text-muted)]">DebtRank · 현재 state · what-if</p>
      </div>

      {/* CHANNEL — depeg(가격) vs liquidity(인출런). depeg은 자산 성질에 맞는 cascade 자동 적용 */}
      <Section tag="채널" title="어떤 전염을 볼까">
        <div className="grid grid-cols-2 gap-1.5">
          {([
            ["depeg", "가격 depeg", "cascade"],
            ["liquidity", "인출런", "유동성"],
          ] as const).map(([k, label, sub]) => (
            <button
              key={k}
              onClick={() => onChange({ channel: k })}
              className={`rounded-md border px-2 py-2 text-center ${
                c.channel === k
                  ? "border-[var(--color-accent)] bg-[rgba(124,131,255,0.12)] text-[var(--color-text-primary)]"
                  : "border-[var(--color-border-subtle)] text-[var(--color-text-muted)]"
              }`}
            >
              <div className="text-[12px] font-semibold">{label}</div>
              <div className="text-[9px] text-[var(--color-text-muted)]">{sub}</div>
            </button>
          ))}
        </div>
        <p className="mt-2 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
          {c.channel === "depeg"
            ? "가격이 δ만큼 빠지면(원인 무관: 민팅·익스플로잇·디페그) 그 자산 성질에 맞는 실제 사건형 cascade를 자동 적용: M1 흡수 + M2 DEX fire-sale + M3 오라클 지연 차익 + M4 인출런 환류. naive(흡수만) 대비 증폭 배수도 표시."
            : "공급자가 동시에 인출하면 못 빼는 자본 (utilization 버퍼 초과). 가격 사건 아님, 손실 아님."}
        </p>
        {c.channel === "depeg" && (
          <label className="mt-2 flex cursor-pointer items-center gap-2 text-[10px] text-[var(--color-text-secondary)]">
            <input type="checkbox" checked={c.naive} onChange={(e) => onChange({ naive: e.target.checked })} />
            naive 바닥값만 (M1 흡수, 증폭 제외 · 반증 기준선)
          </label>
        )}
      </Section>

      {/* LAYER 1 — shock */}
      <Section
        tag="Layer 1 · 충격 대상"
        title={
          isOracle
            ? `공유 오라클 (common-mode)  (${assets.length}개)`
            : c.channel === "liquidity"
              ? `인출런 대상 (공급자산)  (${assets.length}개)`
              : `담보 토큰  (${assets.length}개)`
        }
      >
        {/* search target: tokens vs shared oracles (separate lists, easier to search) */}
        <div className="mb-2 grid grid-cols-2 gap-1.5">
          {([["token", "토큰"], ["oracle", "오라클"]] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => onSearchKindChange(k)}
              className={`rounded-md border px-2 py-1 text-[10px] font-semibold ${
                searchKind === k
                  ? "border-[var(--color-accent)] bg-[rgba(124,131,255,0.12)] text-[var(--color-text-primary)]"
                  : "border-[var(--color-border-subtle)] text-[var(--color-text-muted)]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="relative">
          <input
            value={open ? query : selectedDisplay}
            placeholder={isOracle ? "오라클 검색 (예: Chainlink ETH/USD)" : "토큰 검색 (예: wstETH, USDC)"}
            onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
            onFocus={() => { setOpen(true); setQuery(""); }}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            className="w-full rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-2.5 py-2 text-[12px] text-[var(--color-text-primary)]"
          />
          {open && (
            <div className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] shadow-xl">
              {filtered.length === 0 && (
                <div className="px-2.5 py-2 text-[11px] text-[var(--color-text-muted)]">결과 없음</div>
              )}
              {filtered.map((a) => {
                const isOracle = a.kind === "oracle";
                return (
                  <button
                    key={a.symbol}
                    onMouseDown={(e) => { e.preventDefault(); onChange({ asset: a.symbol }); setOpen(false); }}
                    className={`flex w-full items-center justify-between px-2.5 py-1.5 text-left text-[12px] hover:bg-[var(--color-surface)] ${a.symbol === c.asset ? "bg-[rgba(124,131,255,0.08)]" : ""}`}
                  >
                    <span className="truncate text-[var(--color-text-primary)]">
                      {isOracle ? (a.label ?? a.symbol) : a.symbol}<VenueBadge venues={a.venues} />
                    </span>
                    <span className="shrink-0 pl-2 text-[10px] text-[var(--color-text-muted)]">
                      {isOracle ? `${a.n_markets}자산` : `${a.n_markets}마켓`} · {fmtUsd(a.supply_usd)}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        {selected?.kind === "oracle" && (
          <p className="mt-2 rounded-md border border-[rgba(251,191,36,0.25)] bg-[rgba(251,191,36,0.06)] px-2 py-1.5 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
            공유 오라클 장애 → {selected.affected?.length ?? 0}개 자산 동시 디페그(common-mode).
            {selected.note ? ` ${selected.note}` : ""}
          </p>
        )}
        <div className="mt-3 flex items-center justify-between">
          <span className="text-[11px] text-[var(--color-text-secondary)]">
            {c.channel === "liquidity" ? "인출 강도 ρ" : "가격 depeg δ"}
          </span>
          <span className="font-mono text-[13px] font-bold text-[var(--color-danger)]">
            {c.channel === "depeg" ? "−" : ""}{Math.round(c.delta * 100)}%
          </span>
        </div>
        <input
          type="range" min={5} max={95} step={5}
          value={Math.round(c.delta * 100)}
          onChange={(e) => onChange({ delta: Number(e.target.value) / 100 })}
          className="mt-1 w-full"
        />
      </Section>

      {/* LAYER 2 — model levers */}
      <Section tag="Layer 2 · 모델 파라미터" title="DebtRank 변수 (식에 직결)">
        {/* venues */}
        <p className="mt-3 text-[11px] text-[var(--color-text-secondary)]">프로토콜 (venue)</p>
        <div className="mt-1 grid grid-cols-2 gap-1.5">
          {([["morpho", "Morpho"], ["aave", "Aave"], ["spark", "Spark"], ["skycdp", "Sky CDP"]] as const).map(([k, label]) => (
            <label key={k} className="flex cursor-pointer items-center gap-1.5 rounded-md border border-[var(--color-border-subtle)] px-2 py-1.5 text-[11px] text-[var(--color-text-secondary)]">
              <input
                type="checkbox"
                checked={c[k]}
                onChange={(e) => onChange({ [k]: e.target.checked } as Partial<ContagionControls>)}
              />
              {label}
            </label>
          ))}
        </div>

        {/* freeze (governance blocker) */}
        <p className="mt-3 text-[11px] text-[var(--color-text-secondary)]">동결 (governance freeze)</p>
        <input
          value={c.freeze}
          placeholder="동결할 담보 심볼 csv (예: rsETH,weETH)"
          onChange={(e) => onChange({ freeze: e.target.value })}
          className="mt-1 w-full rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-2 py-1.5 text-[11px] text-[var(--color-text-primary)]"
        />
        <p className="mt-0.5 text-[9px] text-[var(--color-text-muted)]">동결된 노드는 손실은 실현하되 전파 차단(Aave가 kelp 때 rsETH 동결).</p>

        {/* recovery — auto per-asset by default (liquidation mechanics), manual override */}
        <div className="mt-3 flex items-center justify-between">
          <span className="text-[11px] text-[var(--color-text-secondary)]">청산 회수율 r</span>
          <label className="flex cursor-pointer items-center gap-1.5 text-[10px] text-[var(--color-text-secondary)]">
            <input type="checkbox" checked={c.recoveryAuto} onChange={(e) => onChange({ recoveryAuto: e.target.checked })} />
            자동(자산별)
          </label>
        </div>
        {c.recoveryAuto ? (
          <p className="mt-1 rounded-md border border-[var(--color-border-subtle)] px-2 py-1.5 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
            각 시장의 <b>실제 청산 인센티브</b>에서 자동 산정: Morpho는 마켓 <b>LLTV→LIF</b>(r=1/LIF),
            Aave/Spark는 리저브 <b>liquidation penalty</b>(r=1/(1+penalty)). 데이터 없으면 NAV~98%/DEX~95% 폴백.
            DEX 자산은 그 위에 청산 매도→fire-sale(M2)로 깊이 대비 추가 하락.
          </p>
        ) : (
          <>
            <div className="mt-1 flex items-center justify-end">
              <span className="font-mono text-[12px] text-[var(--color-text-primary)]">{Math.round(c.recovery * 100)}%</span>
            </div>
            <input
              type="range" min={50} max={100} step={5}
              value={Math.round(c.recovery * 100)}
              onChange={(e) => onChange({ recovery: Number(e.target.value) / 100 })}
              className="mt-1 w-full"
            />
            <p className="mt-0.5 text-[9px] text-[var(--color-text-muted)]">수동 고정 r. 회수가능 = 담보×(1−δ)×r. DEX-가격 자산은 fire-sale로 추가 하락. NAV/CAPO는 면제.</p>
          </>
        )}

        {/* downstream */}
        <label className="mt-3 flex cursor-pointer items-center gap-2 text-[11px] text-[var(--color-text-secondary)]">
          <input type="checkbox" checked={c.downstream} onChange={(e) => onChange({ downstream: e.target.checked })} />
          downstream 재귀 (볼트 share 재담보, 다단계)
        </label>
      </Section>

      {/* event-discovered hidden cross-protocol dependencies */}
      <div className="border-b border-[var(--color-border-subtle)] px-5 py-3">
        <label className="flex cursor-pointer items-center gap-2 text-[11px] font-semibold text-[var(--color-text-secondary)]">
          <input type="checkbox" checked={c.includeDiscovered}
                 onChange={(e) => onChange({ includeDiscovered: e.target.checked })} />
          숨은 의존성 포함 (이벤트 발견)
        </label>
        <p className="mt-1 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
          선언된 담보 관계엔 안 보이지만 <b>같은 고래가 두 프로토콜에 동시 포지션</b>(co-presence)이라
          강제 디레버리징으로 이어지는 숨은 cross-protocol 경로를 전파에 추가. 행동기반·근사(정확 $ 아님).
        </p>
      </div>

      <div className="px-5 py-4">
        <button
          onClick={onRun}
          disabled={running || !c.asset || (!c.morpho && !c.aave && !c.spark && !c.skycdp)}
          className="w-full rounded-lg bg-[var(--color-accent)] px-4 py-2.5 text-[13px] font-bold text-white disabled:opacity-50"
        >
          {running ? "계산 중…" : "전염 시뮬레이션 실행"}
        </button>
        <p className="mt-2 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
          hop-1(마켓·공급자)=정확 $ (백테스트됨). 다단계=상대 영향도(중심성). 솔벤시 채널만, 유동성 런 제외.
        </p>
      </div>
    </aside>
  );
}
