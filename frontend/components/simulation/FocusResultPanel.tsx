"use client";

import { AnimatePresence, motion, useDragControls } from "framer-motion";
import { Activity, Coins, GripVertical, Hash, Loader2, Maximize2, Minimize2, User, X } from "lucide-react";
import { useRef } from "react";

import type { FocusEventEdge, FocusResult } from "@/lib/api";

interface Props {
  result: FocusResult | null;
  loading: boolean;
  error: string | null;
  zoomActive?: boolean;
  onToggleZoom?: () => void;
  onClose: () => void;
  onSelectNode?: (id: string) => void;
}

const EDGE_LABEL_KR: Record<string, string> = {
  supply: "예치",
  withdraw: "인출",
  borrow: "차입",
  repay: "상환",
  liquidation: "청산",
  repay_via_liquidation: "청산 상환",
  collateral_seized: "담보 압류",
  atoken_transfer: "aToken 전송",
  flashloan: "플래시론",
};

const EDGE_COLOR: Record<string, string> = {
  supply: "var(--color-healthy)",
  withdraw: "var(--color-text-muted)",
  borrow: "var(--color-caution)",
  repay: "var(--color-healthy)",
  liquidation: "var(--color-danger)",
  repay_via_liquidation: "var(--color-danger)",
  collateral_seized: "var(--color-danger)",
};

function KindIcon({ kind }: { kind: string }) {
  if (kind === "address") return <User size={13} />;
  if (kind === "token") return <Coins size={13} />;
  if (kind === "tx") return <Hash size={13} />;
  return <Activity size={13} />;
}

function shortAddr(a: string | null | undefined): string {
  if (!a) return "—";
  return a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a;
}

function fmtAmount(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return v.toFixed(2);
}

export function FocusResultPanel({
  result, loading, error, zoomActive = false, onToggleZoom, onClose, onSelectNode,
}: Props) {
  const show = loading || !!error || (!!result && result.kind !== "empty");
  const hasRelated = (result?.center_node_ids?.length ?? 0) + (result?.related_node_ids?.length ?? 0) > 0;

  // 드래그 영역 제약 (화면 안에서만 움직임)
  const constraintsRef = useRef<HTMLDivElement>(null);

  // 드래그를 헤더에만 한정하려면 motion 의 dragListener=false + dragControls 사용
  const dragControls = useDragControls();

  return (
    <>
      {/* 드래그 영역 제약 (그래프 영역 전체) */}
      <div ref={constraintsRef} className="pointer-events-none absolute inset-0 z-10" />
      <AnimatePresence>
      {show && (
        <motion.div
          drag
          dragControls={dragControls}
          dragListener={false}
          dragMomentum={false}
          dragElastic={0}
          dragConstraints={constraintsRef}
          initial={{ opacity: 0, x: 12 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 12 }}
          transition={{ duration: 0.18 }}
          className="pointer-events-auto absolute right-3 top-[300px] z-30 w-[330px] overflow-hidden rounded-xl border border-[var(--color-border-subtle)] shadow-2xl"
          style={{ backdropFilter: "blur(12px)", backgroundColor: "rgba(19,19,22,0.92)" }}
        >
          {/* Header — 이 영역만 드래그 가능 (dragControls.start) */}
          <div
            onPointerDown={(e) => dragControls.start(e)}
            className="flex cursor-grab items-center gap-2 border-b border-[var(--color-border-subtle)] px-3 py-2 active:cursor-grabbing select-none"
          >
            <GripVertical size={11} className="text-[var(--color-text-muted)]" />
            <KindIcon kind={result?.kind ?? "empty"} />
            <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--color-text-muted)]">
              포커스 분석
            </span>
            {hasRelated && onToggleZoom && (
              <button
                onClick={onToggleZoom}
                title={zoomActive ? "전체 그래프 보기" : "관련 노드만 보기"}
                className={
                  "ml-auto flex items-center gap-1 rounded border px-1.5 py-0.5 text-[9px] font-semibold transition-colors " +
                  (zoomActive
                    ? "border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-[var(--color-accent)]"
                    : "border-[var(--color-border-subtle)] text-[var(--color-text-muted)] hover:border-[var(--color-accent)]/50 hover:text-[var(--color-accent)]")
                }
              >
                {zoomActive ? <Minimize2 size={10} /> : <Maximize2 size={10} />}
                {zoomActive ? "전체 보기" : "이 그래프만"}
              </button>
            )}
            <button
              onClick={onClose}
              className={hasRelated && onToggleZoom ? "ml-1 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors" : "ml-auto text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors"}
            >
              <X size={13} />
            </button>
          </div>

          {/* Body */}
          <div className="max-h-[70vh] overflow-y-auto">
            {loading && (
              <div className="flex items-center justify-center gap-2 px-3 py-6 text-[11px] text-[var(--color-text-muted)]">
                <Loader2 size={13} className="animate-spin" />
                분석 중…
              </div>
            )}

            {error && !loading && (
              <div className="px-3 py-3 text-[11px] text-[var(--color-danger)]">{error}</div>
            )}

            {!loading && !error && result && result.kind === "token" && (
              <TokenResult result={result} onSelectNode={onSelectNode} />
            )}
            {!loading && !error && result && result.kind === "address" && (
              <AddressResult result={result} onSelectNode={onSelectNode} />
            )}
            {!loading && !error && result && result.kind === "tx" && (
              <TxResult result={result} />
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Mini topology — 검색 결과의 1-hop 토폴로지를 SVG 로 작게 표시
// 중앙에 center 노드, 주변에 related 노드를 원형 배치 (radial)
// ─────────────────────────────────────────────────────────────

function MiniTopology({
  centerLabel,
  related,
  onSelectNode,
}: {
  centerLabel: string;
  related: Array<{ id: string; label?: string; category?: string }>;
  onSelectNode?: (id: string) => void;
}) {
  const W = 280;
  const H = 200;
  const cx = W / 2;
  const cy = H / 2;
  const R = 75; // 원형 배치 반경

  if (related.length === 0) {
    return (
      <div className="rounded border border-[var(--color-border-subtle)] p-3 text-center text-[10px] text-[var(--color-text-muted)]">
        연결된 노드 없음
      </div>
    );
  }

  // 노드 타입별 색상 (RiskNode 의 TYPE_META 와 비슷하게)
  const colorOf = (cat?: string): string => {
    if (!cat) return "#818cf8";
    if (cat.includes("oracle") || cat === "price_feed" || cat === "price_adapter") return "#fbbf24";
    if (cat.includes("token") || cat === "underlying_asset") return "#818cf8";
    if (cat === "lst_token" || cat === "lrt_token") return "#34d399";
    if (cat.includes("pool") || cat === "lending" || cat === "treasury") return "#60a5fa";
    return "#94a3b8";
  };

  return (
    <div className="rounded border border-[var(--color-border-subtle)] bg-[var(--color-background)]/40 p-1">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
        {/* 엣지 (center 에서 각 related 로 직선) */}
        {related.slice(0, 12).map((r, i) => {
          const angle = (i / Math.min(related.length, 12)) * 2 * Math.PI - Math.PI / 2;
          const x = cx + Math.cos(angle) * R;
          const y = cy + Math.sin(angle) * R;
          return (
            <line
              key={`line-${r.id}`}
              x1={cx} y1={cy} x2={x} y2={y}
              stroke="var(--color-border-subtle)" strokeWidth={1}
            />
          );
        })}

        {/* Related 노드 (원형 배치) */}
        {related.slice(0, 12).map((r, i) => {
          const angle = (i / Math.min(related.length, 12)) * 2 * Math.PI - Math.PI / 2;
          const x = cx + Math.cos(angle) * R;
          const y = cy + Math.sin(angle) * R;
          const c = colorOf(r.category);
          const labelShort = (r.label || r.id).slice(0, 8);
          return (
            <g
              key={r.id}
              onClick={() => onSelectNode?.(r.id)}
              className="cursor-pointer hover:opacity-100 opacity-85"
            >
              <circle cx={x} cy={y} r={9} fill={c} stroke="rgba(0,0,0,0.4)" strokeWidth={1} />
              <text
                x={x} y={y + 22}
                textAnchor="middle"
                fontSize={8}
                fill="var(--color-text-secondary)"
                className="pointer-events-none select-none"
              >
                {labelShort}
              </text>
            </g>
          );
        })}

        {/* Center 노드 (강조) */}
        <g>
          <circle cx={cx} cy={cy} r={14} fill="var(--color-accent)" stroke="white" strokeWidth={1.5} />
          <text
            x={cx} y={cy + 28}
            textAnchor="middle"
            fontSize={9}
            fontWeight={700}
            fill="var(--color-text-primary)"
            className="pointer-events-none select-none"
          >
            {centerLabel.slice(0, 12)}
          </text>
        </g>

        {/* 잘린 노드 수 표시 */}
        {related.length > 12 && (
          <text
            x={W - 4} y={H - 4}
            textAnchor="end"
            fontSize={8}
            fill="var(--color-text-muted)"
          >
            +{related.length - 12} more
          </text>
        )}
      </svg>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────
// Token result
// ─────────────────────────────────────────────────────────────

function TokenResult({ result, onSelectNode }: { result: FocusResult; onSelectNode?: (id: string) => void }) {
  const n = result.graph_node;
  if (!n) {
    return (
      <div className="px-3 py-4 text-[11px] text-[var(--color-text-muted)]">
        매칭되는 토큰을 찾지 못했습니다. (입력: <span className="font-mono">{result.query}</span>)
      </div>
    );
  }
  const byType = result.related_by_type ?? {};
  return (
    <div className="space-y-3 px-3 py-3">
      <div>
        <button
          onClick={() => onSelectNode?.(n.id)}
          className="text-left text-[14px] font-semibold text-[var(--color-text-primary)] hover:text-[var(--color-accent)] transition-colors"
          title="그래프에서 이 노드 선택"
        >
          {n.label}
        </button>
        <div className="mt-0.5 font-mono text-[9px] text-[var(--color-text-muted)]">{n.id}</div>
      </div>

      {Object.keys(byType).length > 0 && (
        <>
          {/* 미니 토폴로지 */}
          <div>
            <div className="text-[9px] font-bold uppercase tracking-widest text-[var(--color-text-muted)] mb-1">
              토폴로지 미리보기
            </div>
            <MiniTopology
              centerLabel={n.label}
              related={Object.values(byType).flat()}
              onSelectNode={onSelectNode}
            />
          </div>
          <div>
            <div className="text-[9px] font-bold uppercase tracking-widest text-[var(--color-text-muted)]">
              연결된 노드 ({result.related_node_ids?.length ?? 0})
            </div>
            <div className="mt-1.5 space-y-1.5">
              {Object.entries(byType).map(([t, items]) => (
                <div key={t}>
                  <div className="text-[8px] uppercase tracking-wider text-[var(--color-text-muted)]">{t}</div>
                  <div className="mt-0.5 flex flex-wrap gap-1">
                    {items.map((i) => (
                      <button
                        key={i.id}
                        onClick={() => onSelectNode?.(i.id)}
                        className="rounded border border-[var(--color-border-subtle)] px-1.5 py-px text-[9px] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] transition-colors"
                      >
                        {i.label || i.id}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      <EventList events={result.recent_events ?? []} title="최근 이벤트" />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Address result
// ─────────────────────────────────────────────────────────────

function AddressResult({ result, onSelectNode }: { result: FocusResult; onSelectNode?: (id: string) => void }) {
  const n = result.graph_node;
  return (
    <div className="space-y-3 px-3 py-3">
      <div>
        {n ? (
          <button
            onClick={() => onSelectNode?.(n.id)}
            className="text-left text-[12px] font-semibold text-[var(--color-text-primary)] hover:text-[var(--color-accent)] transition-colors"
          >
            {n.label}
          </button>
        ) : (
          <div className="text-[12px] font-semibold text-[var(--color-text-primary)]">외부 주소</div>
        )}
        <div className="mt-0.5 font-mono text-[9px] text-[var(--color-text-muted)]">
          {result.query}
        </div>
        {n?.type && (
          <div className="mt-0.5 text-[9px] uppercase tracking-wider text-[var(--color-text-muted)]">
            type: {n.type}
          </div>
        )}
      </div>

      <div className="rounded border border-[var(--color-border-subtle)] px-2.5 py-2 text-[10px]">
        <div className="flex justify-between">
          <span className="text-[var(--color-text-muted)]">이벤트</span>
          <span className="font-semibold text-[var(--color-text-primary)]">{result.event_count ?? 0}</span>
        </div>
        <div className="mt-1 flex justify-between">
          <span className="text-[var(--color-text-muted)]">카운터파티</span>
          <span className="text-[var(--color-text-primary)]">
            {result.event_counterparties?.length ?? 0}
          </span>
        </div>
        <div className="mt-1 flex justify-between">
          <span className="text-[var(--color-text-muted)]">그래프 1-hop</span>
          <span className="text-[var(--color-text-primary)]">
            {result.related_node_ids?.length ?? 0}
          </span>
        </div>
      </div>

      {/* 미니 토폴로지 — graph_node 가 있을 때만 */}
      {n && (result.related_node_ids?.length ?? 0) > 0 && (
        <div>
          <div className="text-[9px] font-bold uppercase tracking-widest text-[var(--color-text-muted)] mb-1">
            토폴로지 미리보기
          </div>
          <MiniTopology
            centerLabel={n.label}
            related={(result.related_node_ids ?? []).map((id) => ({ id, label: id.slice(0, 10) }))}
            onSelectNode={onSelectNode}
          />
        </div>
      )}

      <EventList events={result.recent_events ?? []} title="최근 활동" />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Tx result
// ─────────────────────────────────────────────────────────────

function TxResult({ result }: { result: FocusResult }) {
  return (
    <div className="space-y-3 px-3 py-3">
      <div>
        <div className="text-[12px] font-semibold text-[var(--color-text-primary)]">트랜잭션</div>
        <div className="mt-0.5 break-all font-mono text-[9px] text-[var(--color-text-muted)]">
          {result.query}
        </div>
      </div>
      {result.error && (
        <div className="text-[11px] text-[var(--color-danger)]">{result.error}</div>
      )}
      <EventList events={result.recent_events ?? []} title={`이 트랜잭션의 엣지 (${result.event_count ?? 0})`} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Shared: Event list
// ─────────────────────────────────────────────────────────────

function EventList({ events, title }: { events: FocusEventEdge[]; title: string }) {
  if (!events.length) {
    return (
      <div>
        <div className="text-[9px] font-bold uppercase tracking-widest text-[var(--color-text-muted)]">
          {title}
        </div>
        <div className="mt-1 text-[10px] text-[var(--color-text-muted)]">데이터 없음</div>
      </div>
    );
  }
  return (
    <div>
      <div className="text-[9px] font-bold uppercase tracking-widest text-[var(--color-text-muted)]">
        {title} (최근 {events.length})
      </div>
      <div className="mt-1.5 space-y-1">
        {events.slice(0, 12).map((e) => (
          <div
            key={e.edge_id}
            className="flex items-center gap-2 rounded border border-[var(--color-border-subtle)] px-2 py-1 text-[10px]"
            style={{ borderLeft: `2px solid ${EDGE_COLOR[e.edge_type] ?? "transparent"}` }}
          >
            <span className="w-14 font-medium text-[var(--color-text-primary)]">
              {EDGE_LABEL_KR[e.edge_type] ?? e.edge_type}
            </span>
            <span className="flex-1 truncate text-[var(--color-text-secondary)]">
              {shortAddr(e.from_address)} → {shortAddr(e.to_address)}
            </span>
            <span className="font-mono text-[var(--color-text-muted)]">
              {fmtAmount(e.amount_decimal)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
