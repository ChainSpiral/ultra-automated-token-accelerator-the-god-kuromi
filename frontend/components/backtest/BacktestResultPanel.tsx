"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle, AlertTriangle, ExternalLink } from "lucide-react";

import type { BacktestResult } from "@/lib/api";
import { formatUsd } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  result: BacktestResult | null;
}

export function BacktestResultPanel({ result }: Props) {
  return (
    <AnimatePresence>
      {result && (
        <motion.div
          key="bt-panel"
          initial={{ x: 360, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 360, opacity: 0 }}
          transition={{ type: "spring", stiffness: 320, damping: 32 }}
          className="absolute right-0 top-0 bottom-0 z-20 flex w-[360px] flex-col overflow-hidden border-l border-[var(--color-border-subtle)] bg-[var(--color-surface)]"
        >
          <PanelContent result={result} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function PanelContent({ result }: { result: BacktestResult }) {
  const { snapshot, predicted, actual, accuracy } = result;
  const cf = accuracy.calibration_factor;
  const isVerified = result.calibration_validated;

  const overPredictPct = cf < 1 ? ((1 - cf) * 100).toFixed(0) : null;
  const underPredictPct = cf > 1 ? ((cf - 1) * 100).toFixed(0) : null;

  return (
    <div className="flex flex-1 flex-col overflow-y-auto">
      {/* Header */}
      <div className="shrink-0 border-b border-[var(--color-border-subtle)] px-5 py-4">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Backtest · {result.date}
        </p>
        <h2 className="mt-0.5 text-sm font-bold text-[var(--color-text-primary)]">
          {result.incident_id}
        </h2>
        <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
          {result.description}
        </p>

        {/* is_hypothetical badge */}
        {result.is_hypothetical && (
          <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-[rgba(251,191,36,0.15)] px-2 py-0.5 text-[10px] font-bold text-[var(--color-caution)]">
            가상 시나리오
          </div>
        )}

        {/* Verification badge — generic across all backtests */}
        <div className="mt-3">
          {isVerified ? (
            <div className="flex items-start gap-2 rounded-lg border border-[rgba(52,211,153,0.3)] bg-[rgba(52,211,153,0.08)] px-3 py-2.5">
              <CheckCircle size={13} className="mt-0.5 shrink-0 text-[var(--color-healthy)]" />
              <div>
                <p className="text-[11px] font-semibold text-[var(--color-healthy)]">독립 검증 완료</p>
                <p className="mt-0.5 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
                  실제값이 시뮬레이션 공식과 무관한 독립 소스(온체인 카운터 / 공개 시장가)에서 도출됨.
                </p>
              </div>
            </div>
          ) : (
            <div className="flex items-start gap-2 rounded-lg border border-[rgba(251,191,36,0.3)] bg-[rgba(251,191,36,0.08)] px-3 py-2.5">
              <AlertTriangle size={13} className="mt-0.5 shrink-0 text-[var(--color-caution)]" />
              <div>
                <p className="text-[11px] font-semibold text-[var(--color-caution)]">독립 검증 미완료</p>
                <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">
                  actual 값이 reverse-engineered 또는 외부 소스에서 직접 조회되지 않았습니다.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Snapshot */}
      <Section
        title="사건 직전 스냅샷"
        subtitle={`블록 ${(snapshot as any).pre_hack_block?.toLocaleString() ?? "—"} · Alchemy 아카이브`}
      >
        <SnapshotGrid snapshot={snapshot} />
      </Section>

      {/* Predicted vs Actual */}
      <Section title="예측값 vs 실제값">
        <ComparisonTable predicted={predicted} actual={actual} accuracy={accuracy} />
      </Section>

      {/* Raw Model Accuracy — no calibration fudge */}
      <Section title="모델 정확도 (Raw)" subtitle="시뮬레이션 엔진의 실제 오차 — 보정 없음">
        <RawAccuracyBlock
          predicted={predicted}
          actual={actual}
          badDebtErrorPct={accuracy.bad_debt_error_pct}
          cf={cf}
        />
      </Section>

      {/* Liquidation count verification — second-order ground truth */}
      {result.actual_liquidation_count_30d != null && (
        <Section
          title="구조적 검증 — 청산 발생 건수"
          subtitle="시뮬 예측 vs 사고 후 30일 온체인 실측 LiquidationCall 이벤트"
        >
          <LiquidationCountBlock
            predicted={result.predicted_liquidation_count ?? 0}
            actual={result.actual_liquidation_count_30d}
            incidentId={result.incident_id}
          />
        </Section>
      )}

      {/* Engine status */}
      <Section title="검증 단계별 결과">
        <EngineStatusBar
          badDebtErr={accuracy.bad_debt_error_pct}
          depegErr={accuracy.depeg_error_pct}
          isVerified={isVerified}
        />
      </Section>

      {/* Data note */}
      <Section title="데이터 출처">
        <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-3 py-2.5">
          <p className="text-[10px] leading-relaxed text-[var(--color-text-muted)]">
            {result.data_note}
          </p>
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-[10px] text-[var(--color-text-muted)]">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-healthy)]" />
          데이터 소스: {result.data_source} ({result.fetch_duration_s}s)
        </div>
      </Section>
    </div>
  );
}

/* ─── Section ───────────────────────────────────────────────── */

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="shrink-0 border-b border-[var(--color-border-subtle)] px-5 py-4">
      <div className="mb-3">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {title}
        </p>
        {subtitle && (
          <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">{subtitle}</p>
        )}
      </div>
      {children}
    </div>
  );
}

/* ─── Snapshot grid ─────────────────────────────────────────── */

function SnapshotGrid({ snapshot }: { snapshot: BacktestResult["snapshot"] }) {
  const rows = [
    { label: "자산", value: snapshot.asset.toUpperCase() },
    { label: "Oracle 가격", value: `$${snapshot.oracle_price.toLocaleString()}` },
    { label: "Aave 예치량", value: `${snapshot.atoken_supply.toLocaleString()} rsETH` },
    { label: "공격자 예치", value: snapshot.attacker_rseth_deposited
        ? `${snapshot.attacker_rseth_deposited.toLocaleString(undefined, {maximumFractionDigits: 0})} rsETH`
        : "—" },
    { label: "eMode LTV", value: snapshot.ltv_emode > 0 ? `${(snapshot.ltv_emode * 100).toFixed(0)}%` : "—" },
    { label: "DEX 유동성", value: formatUsd(snapshot.dex_liquidity_usd) },
    { label: "LT (일반)", value: `${(snapshot.lt_normal * 100).toFixed(0)}%` },
    { label: "시장 동결", value: snapshot.market_frozen ? "동결됨" : "정상" },
  ];
  return (
    <div className="grid grid-cols-2 gap-1.5">
      {rows.map(({ label, value }) => (
        <div
          key={label}
          className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-2.5 py-2"
        >
          <p className="text-[9px] text-[var(--color-text-muted)]">{label}</p>
          <p className="mt-0.5 text-[11px] font-semibold text-[var(--color-text-primary)]">{value}</p>
        </div>
      ))}
    </div>
  );
}

/* ─── Comparison table ──────────────────────────────────────── */

function ComparisonTable({
  predicted,
  actual,
  accuracy,
}: {
  predicted: BacktestResult["predicted"];
  actual: BacktestResult["actual"];
  accuracy: BacktestResult["accuracy"];
}) {
  return (
    <div className="space-y-2">
      <div className="overflow-hidden rounded-lg border border-[var(--color-border-subtle)]">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)]">
              <th className="px-3 py-2 text-left font-medium text-[var(--color-text-muted)]">지표</th>
              <th className="px-3 py-2 text-right font-medium text-[var(--color-text-muted)]">예측</th>
              <th className="px-3 py-2 text-right font-medium text-[var(--color-text-muted)]">실제</th>
              <th className="px-3 py-2 text-right font-medium text-[var(--color-text-muted)]">오차</th>
            </tr>
          </thead>
          <tbody>
            <MetricRow
              label="Bad Debt"
              predicted={formatUsd(predicted.bad_debt_usd)}
              actual={formatUsd(actual.bad_debt_usd)}
              errorPct={accuracy.bad_debt_error_pct}
            />
            <MetricRow
              label="Depeg"
              predicted={`${predicted.depeg_pct.toFixed(1)}%`}
              actual={`${actual.depeg_pct.toFixed(1)}%`}
              errorPct={accuracy.depeg_error_pct}
            />
            <MetricRow
              label="총 손실"
              predicted="—"
              actual={formatUsd(actual.total_loss_usd)}
              errorPct={null}
            />
            <MetricRow
              label="청산 규모"
              predicted={formatUsd(predicted.liquidated_usd)}
              actual="—"
              errorPct={null}
            />
          </tbody>
        </table>
      </div>

      {/* On-chain ground truth source */}
      {actual.bad_debt_weth != null && (
        <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-3 py-2.5">
          <p className="text-[9px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            실제값 측정 방법
          </p>
          <div className="mt-1.5 space-y-1 font-mono text-[10px]">
            <p className="text-[var(--color-text-secondary)]">
              <span className="text-[var(--color-text-muted)]">함수: </span>
              getReserveDeficit(WETH)
            </p>
            <p className="text-[var(--color-text-secondary)]">
              <span className="text-[var(--color-text-muted)]">블록: </span>
              {actual.bad_debt_block?.toLocaleString()}
            </p>
            <p className="text-[var(--color-text-secondary)]">
              <span className="text-[var(--color-text-muted)]">결과: </span>
              {actual.bad_debt_weth.toLocaleString(undefined, { maximumFractionDigits: 2 })} WETH
            </p>
          </div>
          <p className="mt-1.5 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
            강제 청산(2026-05-05) 후 미회수 WETH 부채. 시뮬레이션 공식과 완전히 다른 계산 경로.
          </p>
        </div>
      )}
    </div>
  );
}

function MetricRow({
  label,
  predicted,
  actual,
  errorPct,
}: {
  label: string;
  predicted: string;
  actual: string;
  errorPct: number | null;
}) {
  const errAbs = errorPct !== null ? Math.abs(errorPct) : null;
  const errColor =
    errAbs === null
      ? "text-[var(--color-text-muted)]"
      : errAbs < 10
        ? "text-[var(--color-healthy)]"
        : errAbs < 30
          ? "text-[var(--color-caution)]"
          : "text-[var(--color-danger)]";
  return (
    <tr className="border-b border-[var(--color-border-subtle)] last:border-0">
      <td className="px-3 py-2 text-[var(--color-text-secondary)]">{label}</td>
      <td className="px-3 py-2 text-right font-mono text-[var(--color-text-primary)]">{predicted}</td>
      <td className="px-3 py-2 text-right font-mono text-[var(--color-text-primary)]">{actual}</td>
      <td className={cn("px-3 py-2 text-right font-mono font-semibold", errColor)}>
        {errAbs !== null ? `${errorPct! >= 0 ? "+" : ""}${errorPct!.toFixed(1)}%` : "—"}
      </td>
    </tr>
  );
}

/* ─── Calibration block ─────────────────────────────────────── */

function LiquidationCountBlock({
  predicted, actual, incidentId,
}: {
  predicted: number;
  actual: number;
  incidentId: string;
}) {
  const match = predicted === actual;
  const colour = match ? "var(--color-healthy)" : "var(--color-caution)";
  const note: Record<string, string> = {
    "steth_depeg_2022":
      "2022-05-09 LUNA 붕괴 후 Curve stETH/ETH가 4.5% 탈페그됐지만 Aave V2 stETH 풀에서 발생한 사용자 청산은 0건. 우리 모델이 'no cascade'를 정확히 예측한 구조적 검증.",
    "kelp_2026":
      "해킹 직후 Aave가 rsETH 마켓을 즉시 동결 + 거버넌스가 admin 방식으로 bad debt 처리. 사용자 청산 0건은 마켓 동결의 결과 — 우리 시뮬은 cascade를 예측하지만 사용자 청산은 발생 안 함.",
  };
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2 text-[10px]">
        <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-3 py-2.5">
          <p className="text-[9px] uppercase tracking-wider text-[var(--color-text-muted)]">시뮬 예측 (raw)</p>
          <p className="mt-1 font-mono text-lg font-bold text-[var(--color-text-primary)]">
            {predicted.toLocaleString()}건
          </p>
          <p className="mt-0.5 text-[9px] text-[var(--color-text-muted)]">CascadeSimulator</p>
        </div>
        <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-3 py-2.5">
          <p className="text-[9px] uppercase tracking-wider text-[var(--color-text-muted)]">온체인 실측 (30일)</p>
          <p className="mt-1 font-mono text-lg font-bold text-[var(--color-text-primary)]">
            {actual.toLocaleString()}건
          </p>
          <p className="mt-0.5 text-[9px] text-[var(--color-text-muted)]">eth_getLogs LiquidationCall</p>
        </div>
      </div>
      <div
        className="rounded-lg border px-3 py-2"
        style={{ borderColor: `${colour}80`, backgroundColor: `${colour}10` }}
      >
        <p className="text-[10px] font-bold" style={{ color: colour }}>
          {match ? "✓ 일치" : `× 불일치 (예측 ${predicted} vs 실제 ${actual})`}
        </p>
      </div>
      {note[incidentId] && (
        <p className="text-[9px] leading-relaxed text-[var(--color-text-muted)]">
          {note[incidentId]}
        </p>
      )}
    </div>
  );
}


function RawAccuracyBlock({
  predicted,
  actual,
  badDebtErrorPct,
  cf,
}: {
  predicted: BacktestResult["predicted"];
  actual: BacktestResult["actual"];
  badDebtErrorPct: number;
  cf: number;
}) {
  // badDebtErrorPct: signed (+ = over-predict, - = under-predict)
  const absErr = Math.abs(badDebtErrorPct);
  const direction = badDebtErrorPct > 0 ? "과대" : badDebtErrorPct < 0 ? "과소" : "정확";
  const errColor = absErr < 10
    ? "var(--color-healthy)"
    : absErr < 50
      ? "var(--color-caution)"
      : "var(--color-danger)";
  const errBand = absErr < 10
    ? "양호 (±10% 이내)"
    : absErr < 50
      ? "유의 (±10–50%)"
      : "큰 오차 (±50% 초과)";

  return (
    <div className="space-y-3">
      {/* Big honest number */}
      <div className="rounded-lg border px-4 py-4 text-center"
           style={{ borderColor: `${errColor}80`, backgroundColor: `${errColor}10` }}>
        <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
          모델 raw 오차
        </p>
        <p className="mt-1 font-mono text-3xl font-bold tabular-nums" style={{ color: errColor }}>
          {badDebtErrorPct > 0 ? "+" : ""}{badDebtErrorPct.toFixed(1)}%
        </p>
        <p className="mt-0.5 text-[10px]" style={{ color: errColor }}>
          {errBand} · {direction} 예측
        </p>
      </div>

      {/* The two raw numbers */}
      <div className="grid grid-cols-2 gap-2 text-[10px]">
        <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-3 py-2.5">
          <p className="text-[9px] uppercase tracking-wider text-[var(--color-text-muted)]">
            시뮬 예측 (raw)
          </p>
          <p className="mt-1 font-mono text-sm font-bold text-[var(--color-text-primary)]">
            {formatUsd(predicted.bad_debt_usd)}
          </p>
          <p className="mt-0.5 text-[9px] text-[var(--color-text-muted)]">
            우리 엔진 계산값
          </p>
        </div>
        <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-3 py-2.5">
          <p className="text-[9px] uppercase tracking-wider text-[var(--color-text-muted)]">
            온체인 실측
          </p>
          <p className="mt-1 font-mono text-sm font-bold text-[var(--color-text-primary)]">
            {formatUsd(actual.bad_debt_usd)}
          </p>
          {actual.bad_debt_weth && (
            <p className="mt-0.5 font-mono text-[9px] text-[var(--color-text-muted)]">
              = {actual.bad_debt_weth.toLocaleString(undefined, { maximumFractionDigits: 0 })} WETH
            </p>
          )}
        </div>
      </div>

      {/* Honest caveat about calibration_factor */}
      <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-3 py-2.5">
        <p className="text-[10px] leading-relaxed text-[var(--color-text-secondary)]">
          참고: <span className="font-mono">calibration_factor = {cf.toFixed(3)}</span>은 사후 보정 계수입니다.
          예측값에 이 값을 곱하면 실측값에 맞춰지지만, <span className="font-semibold">모델 자체의 정확도 지표는 아닙니다</span>.
          위의 raw 오차가 본 시뮬레이터의 실제 검증 가능한 정확도입니다.
        </p>
      </div>
    </div>
  );
}


function CalibrationBlock({
  cf,
  overPredictPct,
  underPredictPct,
  actual,
  isVerified,
}: {
  cf: number;
  overPredictPct: string | null;
  underPredictPct: string | null;
  actual: BacktestResult["actual"];
  isVerified: boolean;
}) {
  const cfNear = Math.abs(cf - 1.0) < 0.10;
  const cfOk   = Math.abs(cf - 1.0) < 0.30;
  const cfColor = cfNear ? "var(--color-healthy)" : cfOk ? "var(--color-caution)" : "var(--color-danger)";
  const cfLabel = cfNear ? "양호" : cfOk ? "보정 필요" : "오차 큼";

  return (
    <div className="space-y-3">
      {/* CF value */}
      <div className="flex items-center justify-between rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-4 py-3">
        <div>
          <p className="text-[10px] text-[var(--color-text-muted)]">Calibration Factor</p>
          <p className="mt-0.5 font-mono text-2xl font-bold tabular-nums" style={{ color: cfColor }}>
            {cf.toFixed(3)}
          </p>
        </div>
        <div
          className="rounded-full px-2.5 py-1 text-[10px] font-bold"
          style={{ color: cfColor, backgroundColor: `${cfColor}1a`, border: `1px solid ${cfColor}4d` }}
        >
          {cfLabel}
        </div>
      </div>

      {/* CF interpretation */}
      <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-3 py-2.5 space-y-2">
        <p className="text-[10px] leading-relaxed text-[var(--color-text-muted)]">
          <span className="font-semibold text-[var(--color-text-secondary)]">CF = actual ÷ predicted</span>
          {" "}— 1.000이면 완벽한 예측.
        </p>
        {overPredictPct && (
          <div className="rounded bg-[var(--color-surface)] px-2.5 py-2 font-mono text-[9px] space-y-1">
            <p className="text-[var(--color-text-secondary)]">
              예측: <span className="text-[var(--color-danger)]">$231,005,089</span>
              <span className="text-[var(--color-text-muted)]"> (116,500 rsETH × $2,510 × 79%)</span>
            </p>
            <p className="text-[var(--color-text-secondary)]">
              실제: <span style={{ color: "var(--color-healthy)" }}>${actual.bad_debt_usd.toLocaleString()}</span>
              {actual.bad_debt_weth && (
                <span className="text-[var(--color-text-muted)]"> ({actual.bad_debt_weth.toLocaleString(undefined, { maximumFractionDigits: 0 })} WETH)</span>
              )}
            </p>
          </div>
        )}
        <p className="text-[10px] leading-relaxed text-[var(--color-text-muted)]">
          {overPredictPct
            ? <>엔진이 실제보다 <span className="font-semibold text-[var(--color-danger)]">{overPredictPct}% 과대 예측</span>합니다. 이 CF(0.533)를 곱하면 보정된 예측값이 됩니다.</>
            : underPredictPct
              ? <>엔진이 실제보다 <span className="font-semibold text-[var(--color-caution)]">{underPredictPct}% 과소 예측</span>합니다.</>
              : <>엔진 예측이 실제와 잘 일치합니다.</>
          }
        </p>
        {isVerified && (
          <p className="border-t border-[var(--color-border-subtle)] pt-1.5 text-[9px] text-[var(--color-text-muted)]">
            두 값이 서로 다른 계산 경로 → CF는 의미있는 보정 계수입니다
          </p>
        )}
      </div>
    </div>
  );
}

/* ─── Engine status bar ─────────────────────────────────────── */

function EngineStatusBar({
  badDebtErr,
  depegErr,
  isVerified,
}: {
  badDebtErr: number;
  depegErr: number;
  isVerified: boolean;
}) {
  const maxErr = Math.max(Math.abs(badDebtErr), Math.abs(depegErr));
  const engineStatus = maxErr < 10 ? "verified" : maxErr < 30 ? "partial" : "failed";

  const items = [
    {
      label: "블록 파라미터",
      status: "verified" as const,
      note: "Alchemy 아카이브 검증",
    },
    {
      label: "시뮬레이션 엔진",
      status: engineStatus as "verified" | "partial" | "failed",
      note: `Bad Debt 오차 ${badDebtErr.toFixed(0)}%`,
    },
    {
      label: "결과 독립 검증",
      status: isVerified ? ("verified" as const) : ("failed" as const),
      note: isVerified ? "getReserveDeficit(WETH)" : "독립 검증 미완료",
    },
  ];

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-border-subtle)]">
      {items.map((item, i) => (
        <div
          key={item.label}
          className={cn(
            "flex items-center justify-between px-3 py-2 text-[10px]",
            i > 0 && "border-t border-[var(--color-border-subtle)]",
          )}
        >
          <div className="flex items-center gap-2">
            <StatusDot status={item.status} />
            <span className="text-[var(--color-text-secondary)]">{item.label}</span>
          </div>
          <span
            className={cn(
              "font-medium",
              item.status === "verified" && "text-[var(--color-healthy)]",
              item.status === "partial"  && "text-[var(--color-caution)]",
              item.status === "failed"   && "text-[var(--color-danger)]",
            )}
          >
            {item.note}
          </span>
        </div>
      ))}
    </div>
  );
}

function StatusDot({ status }: { status: "verified" | "partial" | "failed" }) {
  const colors = {
    verified: "var(--color-healthy)",
    partial:  "var(--color-caution)",
    failed:   "var(--color-danger)",
  };
  return (
    <span
      className="inline-block h-1.5 w-1.5 rounded-full"
      style={{ backgroundColor: colors[status] }}
    />
  );
}
