"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle, AlertTriangle } from "lucide-react";

import type { ContagionResult, ContagionComparison } from "@/lib/api";
import { formatUsd } from "@/lib/api";

interface Props {
  data: ContagionResult | null;
}

export function ContagionResultPanel({ data }: Props) {
  return (
    <AnimatePresence>
      {data && (
        <motion.div
          key="contagion-panel"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="absolute right-0 top-0 bottom-0 z-20 flex w-[380px] flex-col overflow-hidden border-l border-[var(--color-border-subtle)] bg-[var(--color-surface)]"
        >
          <PanelContent data={data} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function ModeBlock({ title, c, good }: { title: string; c: ContagionComparison; good: boolean }) {
  return (
    <div
      className="rounded-lg border px-3 py-2.5"
      style={{
        borderColor: good ? "rgba(52,211,153,0.3)" : "rgba(251,191,36,0.3)",
        background: good ? "rgba(52,211,153,0.06)" : "rgba(251,191,36,0.06)",
      }}
    >
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-bold text-[var(--color-text-primary)]">{title}</p>
        <div className="flex items-center gap-2 text-[10px] font-mono text-[var(--color-text-secondary)]">
          <span>recall {c.recall ?? "—"}</span>
          <span>prec {c.precision}</span>
        </div>
      </div>
      <p className="mt-1 text-[10px] text-[var(--color-text-muted)]">
        예측 victim {c.n_predicted_victims} · 실제 {c.n_actual_victims} · 예측손실 {formatUsd(c.predicted_loss_total_usd)}
      </p>
      {c.false_positives.length > 0 && (
        <div className="mt-1.5">
          <p className="text-[10px] font-semibold text-[var(--color-caution)]">
            False positives ({c.false_positives.length}):
          </p>
          {c.false_positives.map((f) => (
            <p key={f.label} className="text-[10px] text-[var(--color-text-muted)]">
              · {f.label} — {formatUsd(f.predicted_loss_usd)} (실제 손실 없음)
            </p>
          ))}
        </div>
      )}
      {c.false_positives.length === 0 && (
        <p className="mt-1.5 text-[10px] text-[var(--color-healthy)]">False positive 0 — 정확히 일치</p>
      )}
    </div>
  );
}

function LiveBody({ data }: { data: ContagionResult }) {
  const imp = data.impact;
  if (!imp) return null;
  const affected = imp.top_vaults.filter((v) => v.h >= 0.01);
  const channel = imp.channel ?? "depeg";
  const isLiq = channel === "liquidity";
  const isDepeg = channel === "depeg";
  const isNaive = !!imp.naive;
  const active = imp.mechanisms ?? [];
  const mechRow = (key: string, label: string, usd: number | undefined, extra?: string) => {
    const on = active.includes(key);
    return (
      <div className={`flex justify-between ${on ? "" : "opacity-40"}`}>
        <span className="text-[var(--color-text-muted)]">{label}{extra && on ? ` ${extra}` : ""}</span>
        <span className="font-mono">{on ? formatUsd(usd ?? 0) : "미적용"}</span>
      </div>
    );
  };
  return (
    <>
      <div className="flex items-start gap-2 rounded-lg border border-[rgba(99,102,241,0.3)] bg-[rgba(99,102,241,0.08)] px-3 py-2.5">
        <CheckCircle size={13} className="mt-0.5 shrink-0 text-[var(--color-accent)]" />
        <p className="text-[11px] leading-relaxed text-[var(--color-text-secondary)]">{data.headline}</p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-[var(--color-border-subtle)] px-3 py-2">
          <p className="text-[10px] text-[var(--color-text-muted)]">
            {isLiq ? "동결 자본 (hop-1)" : "검증 bad debt (hop-1)"}
          </p>
          <p className="text-sm font-bold text-[var(--color-danger)]">
            {formatUsd(isLiq ? (imp.total_frozen_usd ?? 0) : imp.total_bad_debt_usd)}
          </p>
        </div>
        <div className="rounded-lg border border-[var(--color-border-subtle)] px-3 py-2">
          <p className="text-[10px] text-[var(--color-text-muted)]">시스템 영향도 (상대)</p>
          <p className="text-sm font-bold text-[var(--color-caution)]">{imp.systemic_impact_score ?? "—"}<span className="text-[10px] text-[var(--color-text-muted)]">/100</span></p>
        </div>
      </div>

      {/* depeg cascade: per-mechanism contribution (M1–M4), gated by asset properties */}
      {isDepeg && !isNaive && (
        <div className="rounded-lg border border-[rgba(251,191,36,0.3)] bg-[rgba(251,191,36,0.06)] px-3 py-2 text-[10px]">
          <p className="mb-1 text-[9px] font-semibold text-[var(--color-text-secondary)]">
            메커니즘 기여 분해 — 가격 depeg이 원인, 자산 성질로 게이트
          </p>
          {mechRow("absorption", "M1 흡수 (초과담보)", imp.mech_absorption_usd)}
          <div className="mt-0.5">{mechRow("firesale", "M2 DEX fire-sale", imp.mech_firesale_usd)}</div>
          <div className="mt-0.5">{mechRow("oracle_lag", "M3 오라클 지연 차익", imp.mech_oracle_lag_usd,
            `(드레인 ${formatUsd(imp.oracle_lag_drain_usd ?? 0)})`)}</div>
          <div className="mt-0.5">{mechRow("run_feedback", "M4 인출런 환류", imp.mech_run_feedback_usd,
            `(ρ ${((imp.run_intensity ?? 0) * 100).toFixed(0)}% → 실효 −${((imp.price_delta_effective ?? 0) * 100).toFixed(0)}%)`)}</div>
          <div className="mt-1.5 flex justify-between border-t border-[var(--color-border-subtle)] pt-1 font-semibold">
            <span className="text-[var(--color-text-secondary)]">합계 bad debt</span>
            <span className="font-mono text-[var(--color-text-primary)]">{formatUsd(imp.total_bad_debt_usd)}</span>
          </div>
          <div className="mt-0.5 flex justify-between">
            <span className="text-[var(--color-text-muted)]">naive 바닥값(흡수만) 대비</span>
            <span className="font-mono">
              {formatUsd(imp.naive_floor_usd ?? 0)} → <b>{imp.amplification_x ?? 1}×</b> 증폭
            </span>
          </div>
          {(imp.total_frozen_usd ?? 0) > 0 && (
            <div className="mt-0.5 flex justify-between">
              <span className="text-[var(--color-text-muted)]">+ 동결 자본 (M4 유동성, 손실 아님)</span>
              <span className="font-mono">{formatUsd(imp.total_frozen_usd ?? 0)}</span>
            </div>
          )}
        </div>
      )}

      {/* event-discovered hidden cross-protocol bridges (behavioral tier) */}
      {(imp.n_hidden_paths ?? 0) > 0 && (
        <div className="rounded-lg border border-[rgba(168,85,247,0.35)] bg-[rgba(168,85,247,0.07)] px-3 py-2 text-[10px]">
          <p className="mb-1 text-[9px] font-semibold text-[#c4a5f5]">
            숨은 cross-protocol 경로 — 이벤트 발견 (선언 회계엔 안 보임)
          </p>
          {(imp.hidden_paths ?? []).map((p, idx) => (
            <div key={idx} className="mt-0.5">
              <div className="flex justify-between">
                <span className="text-[var(--color-text-secondary)]">
                  {p.from_venue} → {p.to_venue}
                  {p.kind === "issuer"
                    ? <span className="text-[var(--color-text-muted)]"> · {p.asset ?? "토큰"} 강제매도</span>
                    : <span className="text-[var(--color-text-muted)]"> · 강제 디레버리징</span>}
                  <span className="text-[var(--color-text-muted)]"> · 공유고래 {p.shared_whales}명</span>
                </span>
                <span className="font-mono text-[#c4a5f5]">
                  {p.quantified === false ? "노출 미정량" : formatUsd(p.at_risk_usd)}
                </span>
              </div>
              <div className="flex justify-between text-[9px] text-[var(--color-text-muted)]">
                <span>{p.tier} · {p.source} · w={p.w}</span>
                {p.quantified !== false && <span>총 노출 {formatUsd(p.exposure_usd)}</span>}
              </div>
            </div>
          ))}
          <p className="mt-1 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
            같은 고래가 두 프로토콜에 동시 포지션/이동 → 한쪽이 터지면 <b>강제 디레버리징</b>(대출 venue)이나
            <b> 강제 LST 매도</b>(발행자)로 전파. 행동기반·근사(정확 $ 아님, w로 할인). 일부는 노출 금액 미정량.
            선언 그래프가 못 보는 경로.
          </p>
        </div>
      )}

      {isDepeg && isNaive && (
        <p className="rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
          <b>naive 바닥값.</b> M1 초과담보 흡수만 계산(fire-sale·오라클지연·인출런 환류 제외). 실제 사건형
          cascade가 이 바닥값을 얼마나 증폭시키는지 비교하는 <b>반증 기준선</b>.
        </p>
      )}

      {isLiq && (
        <p className="text-[9px] leading-relaxed text-[var(--color-text-muted)]">
          <b>동결 ≠ 손실.</b> utilization(차입/공급)이 높을수록 인출런 시 공급자가 못 빼는 자본이 커짐.
          여유 유동성(1−U) 버퍼를 넘는 인출 수요만 동결. 가격은 멀쩡할 수 있음.
        </p>
      )}
      <p className="text-[9px] leading-relaxed text-[var(--color-text-muted)]">
        hop-1(마켓·직접 공급자)은 회계 기반 <b>정확 $</b>(백테스트됨). 시스템 영향도는 네트워크 중심성 기반
        <b> 상대 점수</b>(DebtRank) — 정확한 다단계 $는 주장 안 함. downstream 노드 {imp.n_downstream_nodes ?? 0}개.
      </p>
      {/* paper-grounded indicators */}
      <div className="rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-[10px]">
        <div className="flex justify-between">
          <span className="text-[var(--color-text-muted)]">λmax (Λ 스펙트럼반경, Bardoscia)</span>
          <span className="font-mono">{imp.lambda_max ?? 0} {imp.stable === false ? "⚠ 증폭영역(>1)" : "안정(<1)"}</span>
        </div>
        {!isLiq && (
          <div className="mt-0.5 flex justify-between">
            <span className="text-[var(--color-text-muted)]">오라클 채널</span>
            <span className="font-mono">
              {imp.shock_oracle_type === "nav" ? "NAV/CAPO — DEX fire-sale OFF"
                : imp.shock_oracle_type === "common_mode" ? "common-mode (다중자산)"
                : "DEX-priced — fire-sale 적용"}
            </span>
          </div>
        )}
      </div>

      {/* cross-protocol split — venue별 귀속 (역할 명시) */}
      <div className="rounded-lg border border-[var(--color-border-subtle)] px-3 py-2">
        <p className="text-[10px] font-semibold text-[var(--color-text-secondary)]">
          {isLiq ? "venue별 동결 자본 (역할)" : "venue별 bad debt (역할)"}
        </p>
        <div className="mt-1 flex flex-col gap-0.5 text-[10px]">
          <div className="flex justify-between">
            <span className="text-[var(--color-text-muted)]">Morpho <span className="opacity-60">— 상세 그래프(마켓·볼트)</span></span>
            <span className="font-mono">{formatUsd(imp.morpho_bad_debt_usd ?? 0)}</span>
          </div>
          {(imp.pendle_pt_bad_debt_usd ?? 0) > 0 && (
            <div className="flex justify-between pl-3">
              <span className="text-[var(--color-text-muted)]">↳ 그중 Pendle PT 담보 <span className="opacity-60">— fire-sale=Pendle 풀</span></span>
              <span className="font-mono">{formatUsd(imp.pendle_pt_bad_debt_usd ?? 0)}</span>
            </div>
          )}
          {(imp.position_venues ?? []).map((v) => (
            <div key={v.venue} className="flex justify-between">
              <span className="text-[var(--color-text-muted)]">
                {v.venue} <span className="opacity-60">— {v.venue === "Sky CDP" ? "ilk 단위(근사)" : "포지션 레벨(top-200 근사)"}</span>
              </span>
              <span className="font-mono">{formatUsd(v.total_bad_debt_usd ?? 0)}</span>
            </div>
          ))}
        </div>
        <p className="mt-1 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
          Morpho만 모든 market/vault를 상세 그래프로 그림. Aave/Spark/Sky는 별도 계산 후 venue 노드로 합산(근사).
          Pendle은 PT 담보(Morpho에 포함)이고 청산 depth는 Pendle AMM 풀.
        </p>
      </div>

      {/* data quality / provenance */}
      {imp.data_quality && (
        <div className="rounded-lg border border-[rgba(251,191,36,0.25)] bg-[rgba(251,191,36,0.05)] px-3 py-2">
          <p className="text-[10px] font-semibold text-[var(--color-text-secondary)]">데이터 출처·근사</p>
          <div className="mt-1 flex flex-col gap-0.5 text-[9px] text-[var(--color-text-muted)]">
            {Object.entries(imp.data_quality).map(([k, v]) => (
              <div key={k}><span className="font-semibold">{k}</span>: {v}</div>
            ))}
            {(imp.shock_dex_depth_usd ?? 0) > 0 && (
              <div><span className="font-semibold">청산 depth</span>: {formatUsd(imp.shock_dex_depth_usd ?? 0)} (DEX-priced)</div>
            )}
          </div>
        </div>
      )}

      {/* position-venue (Aave/Spark) per-borrowed-asset breakdown */}
      {(imp.position_venues ?? []).map((v) => v.bad_debt_by_asset && (
        <div key={v.venue}>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            {v.venue} 차입자산별 bad debt
            <span className="ml-1 normal-case text-[var(--color-text-muted)]">
              (스캔한 top-{v.n_accounts_scanned ?? 200} 중 {v.n_liquidatable} 청산 · 전수 아님, 근사)
            </span>
          </p>
          <div className="mt-1.5 flex flex-col gap-1">
            {Object.entries(v.bad_debt_by_asset).map(([sym, usd]) => (
              <div key={sym} className="flex items-center justify-between text-[10px]">
                <span className="text-[var(--color-text-secondary)]">{sym} 공급자</span>
                <span className="font-mono text-[var(--color-text-muted)]">{formatUsd(usd)}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {isLiq ? "가장 많이 동결된 마켓" : "가장 영향 큰 마켓"}
        </p>
        <div className="mt-1.5 flex flex-col gap-1">
          {imp.top_markets.slice(0, 6).map((m) => (
            <div key={m.node} className="flex items-center justify-between text-[10px]">
              <span className="truncate text-[var(--color-text-secondary)]">
                {m.label}
                {isLiq && m.utilization != null && (
                  <span className="ml-1 text-[var(--color-text-muted)]">U={(m.utilization * 100).toFixed(0)}%</span>
                )}
              </span>
              <span className="ml-2 shrink-0 font-mono text-[var(--color-text-muted)]">
                {(m.h * 100).toFixed(0)}% · {formatUsd(m.bad_debt_usd)}
              </span>
            </div>
          ))}
        </div>
      </div>
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {isLiq ? "동결된 볼트" : "영향받는 볼트"} ({affected.length})
        </p>
        <div className="mt-1.5 flex flex-col gap-1">
          {imp.top_vaults.slice(0, 8).map((v) => (
            <div key={v.node} className="flex items-center justify-between text-[10px]">
              <span className="truncate text-[var(--color-text-secondary)]">{v.label}</span>
              <span className="ml-2 shrink-0 font-mono text-[var(--color-text-muted)]">
                {(v.h * 100).toFixed(0)}% · {formatUsd(v.loss_usd)}
              </span>
            </div>
          ))}
        </div>
      </div>
      <p className="text-[9px] leading-relaxed text-[var(--color-text-muted)]">
        {isLiq
          ? "현재 Morpho state 기준 what-if · 유동성(인출런) 채널 · liq_h=max(0,U+ρ−1) · 파라미터 피팅 없음."
          : isNaive
            ? "현재 Morpho state 기준 what-if · depeg naive 바닥값(M1 흡수만) · 반증 기준선."
            : "현재 Morpho state 기준 what-if · depeg→cascade(M1 흡수+M2 fire-sale+M3 오라클지연+M4 인출런환류) · 자산 성질 게이트 · 사건 보정."}
      </p>
    </>
  );
}

function PanelContent({ data }: { data: ContagionResult }) {
  const { event, ground_truth: gt } = data;
  const isMagnitude = data.kind === "magnitude";
  const isLive = data.kind === "live";
  const channel = data.impact?.channel ?? data.channel ?? "depeg";
  const isLiq = channel === "liquidity";
  const isNaive = !!data.impact?.naive;
  const pct = (event.delta * 100).toFixed(0);

  return (
    <div className="flex flex-1 flex-col overflow-y-auto">
      <div className="shrink-0 border-b border-[var(--color-border-subtle)] px-5 py-4">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {isLive ? "Live What-if · 현재 state" : `Contagion Backtest · ${event.date}`}
        </p>
        <h2 className="mt-0.5 text-sm font-bold text-[var(--color-text-primary)]">
          {isLive
            ? isLiq
              ? `${event.shock_node} 인출런 ρ=${pct}% — 유동성 전염`
              : isNaive
              ? `${event.shock_node} −${pct}% naive 바닥값 — 흡수만`
              : `${event.shock_node} −${pct}% depeg — 실제 사건형 cascade`
            : isMagnitude
            ? `${event.shock_node} 충격 — cross-protocol bad debt`
            : `${event.shock_node} 디페그 — DebtRank 전파`}
        </h2>
        <p className="mt-1 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
          {isLive
            ? isLiq
              ? `현재 Morpho state에서 ${event.shock_node} 공급자의 ${pct}%가 동시에 인출하면 — utilization 버퍼를 넘는 동결 자본을 DebtRank로 전파.`
              : isNaive
              ? `${event.shock_node} −${pct}% — M1 초과담보 흡수만(증폭 제외). cascade 대비 반증 기준선.`
              : `${event.shock_node} −${pct}% 가격 depeg → 자산 성질에 맞는 cascade(흡수+fire-sale+오라클지연+인출런환류) 자동 적용.`
            : isMagnitude
            ? `${event.description ? event.description + " " : ""}${event.shock_node} −${(event.delta * 100).toFixed(0)}% · 사건 직전(${event.pre_shock_date}) 회계 기반 bad debt 계산. 파라미터 피팅 없음.`
            : `${event.usr_pre_price ? `USR $${event.usr_pre_price.toFixed(3)} → $${event.usr_trough_price?.toFixed(3)} ` : ""}(−${(event.delta * 100).toFixed(0)}%). 사건 직전(${event.pre_shock_date}) Morpho 회계 스냅샷으로 전파 계산. 파라미터 피팅 없음.`}
        </p>
      </div>

      <div className="flex flex-col gap-3 px-5 py-4">
        {/* Validation verdict */}
        <div className="flex items-start gap-2 rounded-lg border border-[rgba(52,211,153,0.3)] bg-[rgba(52,211,153,0.08)] px-3 py-2.5">
          <CheckCircle size={13} className="mt-0.5 shrink-0 text-[var(--color-healthy)]" />
          <p className="text-[11px] leading-relaxed text-[var(--color-text-secondary)]">
            {data.headline}
          </p>
        </div>

        {isLive ? (
          <LiveBody data={data} />
        ) : isMagnitude ? (
          <MagnitudeBody data={data} />
        ) : (
          <VaultRecallBody data={data} />
        )}
      </div>
    </div>
  );
}

function MagnitudeBody({ data }: { data: ContagionResult }) {
  const rows = data.comparison_rows ?? [];
  const dist = data.distribution;
  const fmt = (v: number | null | undefined, unit?: string) =>
    v == null ? "—" : unit === "pct" ? `${v}%` : formatUsd(v);
  const channel = data.impact?.channel ?? data.channel;
  const title = channel === "liquidity" ? "예측 vs 실측 (유동성)"
    : channel === "oracle" ? "예측 vs 실측 디페그 (common-mode)"
    : channel === "firesale" ? "예측 vs 실측 bad debt (fire-sale)"
    : "예측 vs 실측 bad debt (venue별)";
  return (
    <>
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {title}
        </p>
        <div className="mt-1.5 flex flex-col gap-2">
          {rows.map((r) => (
            <div key={r.label} className="rounded-lg border border-[var(--color-border-subtle)] px-3 py-2">
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-bold text-[var(--color-text-primary)]">{r.label}</p>
                <span className="text-[10px] font-mono text-[var(--color-text-secondary)]">
                  오차 {r.error_pct ?? "—"}%
                </span>
              </div>
              <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">
                예측 <span className="font-mono">{fmt(r.predicted_usd, r.unit)}</span> · 실측{" "}
                <span className="font-mono">{fmt(r.actual_usd, r.unit)}</span>
              </p>
            </div>
          ))}
        </div>
      </div>

      {dist && (
        <div className="rounded-lg border border-[rgba(52,211,153,0.3)] bg-[rgba(52,211,153,0.06)] px-3 py-2.5">
          <p className="text-[10px] font-semibold text-[var(--color-text-secondary)]">
            cross-protocol 분포
          </p>
          <p className="mt-1 text-[11px] text-[var(--color-text-secondary)]">
            Aave 집중도 — 예측 <b>{dist.predicted_aave_pct}%</b> vs 실측 <b>{dist.actual_aave_pct}%</b>
          </p>
          <p className="mt-1 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
            {data.ground_truth?.distribution_note}
          </p>
        </div>
      )}
    </>
  );
}

function VaultRecallBody({ data }: { data: ContagionResult }) {
  const gt = data.ground_truth;
  const comparison = data.comparison;
  if (!gt) return null;
  return (
    <>
      {/* Ground truth */}
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Ground truth (share-price 손상)
        </p>
        <div className="mt-1.5 rounded-lg border border-[var(--color-border-subtle)] px-3 py-2">
          <p className="text-[11px] text-[var(--color-text-secondary)]">
            솔벤시 손실 합계: <span className="font-mono font-bold">{formatUsd(gt.solvency_loss_total_usd ?? 0)}</span>
          </p>
          {(gt.solvency_victims ?? []).map((v) => (
            <p key={v.address} className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">
              · {v.name} — 손상 {(v.impairment_frac * 100).toFixed(0)}% · {formatUsd(v.loss_usd)}
            </p>
          ))}
        </div>
      </div>

      {/* Solvency vs naive */}
      {comparison && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            모델 비교 (vs ground truth)
          </p>
          <div className="mt-1.5 flex flex-col gap-2">
            <ModeBlock title="Solvency DebtRank (초과담보 인식)" c={comparison.solvency} good />
            <ModeBlock title="Naive (노출비율 × δ)" c={comparison.naive} good={false} />
          </div>
        </div>
      )}

      {/* Channel separation honesty */}
      <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-3 py-2.5">
        <div className="flex items-center gap-1.5">
          <AlertTriangle size={12} className="text-[var(--color-caution)]" />
          <p className="text-[10px] font-semibold text-[var(--color-text-secondary)]">
            채널 구분 (유동성 = 범위 밖)
          </p>
        </div>
        <p className="mt-1 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
          아래는 totalAssets가 빠졌지만 share price는 그대로 = <b>인출(run)</b>이지 bad debt 아님.
          솔벤시 모델 검증 대상에서 제외:
        </p>
        {(gt.liquidity_only_drops ?? []).map((d) => (
          <p key={d.name} className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">
            · {d.name} — 인출 {formatUsd(d.totalassets_drop_usd)}
          </p>
        ))}
      </div>
    </>
  );
}
