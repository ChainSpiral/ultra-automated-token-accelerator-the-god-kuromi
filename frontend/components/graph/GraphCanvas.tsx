"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  type NodeMouseHandler,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesInitialized,
  useNodesState,
  useReactFlow,
  type OnNodeDrag,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { GraphEdge, NodeTickState, RiskLevel, TopologyResponse } from "@/lib/api";
import { SAFE_NODE_STATE } from "@/lib/api";
import { FloatingEdge, type FloatingEdgeType } from "./FloatingEdge";
import { RiskNode, type RiskNodeType } from "./RiskNode";

const nodeTypes = { risk: RiskNode };
const edgeTypes = { floating: FloatingEdge };

const SEVERITY: Record<RiskLevel, number> = { safe: 0, caution: 1, danger: 2 };

// Scale the curated position coordinates for ~190px-wide node cards
const LAYOUT_SCALE_X = 1.5;
const LAYOUT_SCALE_Y = 1.55;

export interface GraphCanvasProps {
  graphKey: string;
  topology: TopologyResponse;
  nodeStates: Record<string, NodeTickState>;
  walletHighlightIds?: Set<string>;
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
  /** Phase 4: 검색 결과의 중심 노드 ID — 이 노드들 주변으로 카메라 이동. */
  focusCenterIds?: string[];
  /** Phase 4 옵션 C: 포커스 줌 모드 — 이 셋에 포함된 노드만 표시 (나머지 hidden). */
  focusOnlyIds?: Set<string> | null;
  /** 전염 애니메이션: 라운드마다 카메라가 활성(전파된) 노드 영역을 따라가게. */
  cameraFollow?: boolean;
}

export function GraphCanvas(props: GraphCanvasProps) {
  return (
    <ReactFlowProvider key={props.graphKey}>
      <GraphCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

// d3-force node type (extends SimulationNodeDatum)
interface D3Node extends SimulationNodeDatum {
  id: string;
  rfId: string;
  // 원래 레이아웃 좌표 — forceX/forceY 앵커가 사용. 드래그 후 "집으로 살짝 돌아가려는" 성향.
  homeX: number;
  homeY: number;
}

function GraphCanvasInner({
  topology,
  nodeStates,
  walletHighlightIds,
  selectedNodeId,
  onSelectNode,
  focusCenterIds,
  focusOnlyIds,
  cameraFollow,
}: GraphCanvasProps) {

  const initialNodes = useMemo<RiskNodeType[]>(
    () =>
      topology.nodes.map((n) => ({
        id: n.id,
        type: "risk",
        position: {
          x: (n.position?.x ?? 0) * LAYOUT_SCALE_X,
          y: (n.position?.y ?? 0) * LAYOUT_SCALE_Y,
        },
        draggable: true,
        data: {
          node: n,
          state: SAFE_NODE_STATE,
          walletHighlight: false,
        },
      })),
    [topology],
  );

  const initialEdges = useMemo<FloatingEdgeType[]>(
    () =>
      topology.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: "floating",
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color: "#52525b",
        },
        data: {
          edgeType: e.type,
          active: false,
          danger: false,
          tier: e.tier,
          bridge: e.bridge,
          sharedWhales: e.sharedWhales,
        },
      })),
    [topology],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState<RiskNodeType>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FloatingEdgeType>(initialEdges);

  // d3-force simulation ref
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const simRef = useRef<any>(null);
  const d3NodesRef = useRef<D3Node[]>([]);
  const animFrameRef = useRef<number | null>(null);

  // 현재 드래그 중인 노드 ID (custom force 가 참조)
  const dragNodeIdRef = useRef<string | null>(null);

  // 노드 ID → 인접 노드 ID Set (1-hop 이웃 빠르게 찾기 위함)
  const neighborsMapRef = useRef<Map<string, Set<string>>>(new Map());

  // 노드 영구 고정 (드래그 후 그 자리에 둠 — 사용자가 reset 하기 전까지)
  // ※ d3n.fx/fy 는 simulation 내부 상태. React 와 분리.
  // ※ "리셋" 은 별도 버튼 또는 새로고침으로.

  // ── 엣지 타입별 link strength (오라클/프로토콜 연결은 강하게)
  //    범위 0~1. 클수록 link 가 더 강하게 노드를 끌어당김.
  const EDGE_STRENGTH: Record<string, number> = {
    oracle:     0.40,  // 자산 → 오라클: 같은 피드 의존 자산들이 오라클 주위에 모임
    protocol:   0.30,  // 프로토콜 위임/관리: 관련 컨트랙트 클러스터
    issued_by:  0.30,  // 발행자 → 발행 자산
    restaked:   0.30,
    collateral: 0.15,  // 토큰 ↔ lending 프로토콜
    dex:        0.08,
    yield:      0.08,
    exploit:    0.10,
    deploy:     0.05,
    contagion:  0.05,
  };
  const DEFAULT_EDGE_STRENGTH = 0.05;

  // ── 엣지 타입별 목표 거리 (강한 link 는 가깝게)
  const EDGE_DISTANCE: Record<string, number> = {
    oracle:     140,
    protocol:   160,
    issued_by:  150,
    restaked:   160,
    collateral: 220,
    dex:        260,
    yield:      260,
  };
  const DEFAULT_EDGE_DISTANCE = 260;

  // ── 노드 타입별 충돌 반경 / charge (크기 차등에 맞춤)
  function getNodeRadius(nodeId: string): number {
    const tn = topology.nodes.find((n) => n.id === nodeId);
    if (!tn) return 60;
    const md = (tn.metadata ?? {}) as Record<string, unknown>;
    const cat = (md.category as string | undefined) ?? "";
    const discovered = !!md.discovered;
    if (tn.type === "Oracle" || cat === "protocol_pool" || cat === "market_registry" ||
        cat === "treasury" || cat === "stability_module" || cat === "lending" ||
        cat === "restaking" || cat === "chain") return 110;
    if (discovered && (cat === "a_token" || cat === "variable_debt_token" ||
        cat === "price_feed" || cat === "price_adapter")) return 32;
    if (cat === "a_token" || cat === "variable_debt_token" ||
        cat === "price_feed" || cat === "price_adapter") return 32;
    if (cat === "lst_token" || cat === "lrt_token" || cat === "stable_token") return 85;
    if (cat === "underlying_asset") return 65;
    return 75;
  }

  function getNodeCharge(nodeId: string): number {
    const r = getNodeRadius(nodeId);
    if (r >= 110) return -1000;  // 인프라 — 강하게 밀어내 영역 확보
    if (r >= 80)  return -500;
    if (r >= 60)  return -350;
    return -150;                  // icon-only — 좁은 공간
  }

  // Initialize d3-force simulation
  useEffect(() => {
    const d3Nodes: D3Node[] = topology.nodes.map((n) => {
      const hx = (n.position?.x ?? 0) * LAYOUT_SCALE_X;
      const hy = (n.position?.y ?? 0) * LAYOUT_SCALE_Y;
      return {
        id: n.id,
        rfId: n.id,
        x: hx,
        y: hy,
        homeX: hx,
        homeY: hy,
      };
    });

    const d3Links: (SimulationLinkDatum<D3Node> & { etype?: string })[] = topology.edges
      .map((e) => ({
        source: e.source,
        target: e.target,
        etype: e.type,
      }))
      .filter((l) => {
        const hasSource = d3Nodes.some((n) => n.id === l.source);
        const hasTarget = d3Nodes.some((n) => n.id === l.target);
        return hasSource && hasTarget;
      });

    d3NodesRef.current = d3Nodes;

    // 인접 맵 (1-hop 이웃) — drag attract force 가 사용
    const adj = new Map<string, Set<string>>();
    for (const n of d3Nodes) adj.set(n.id, new Set());
    for (const l of d3Links) {
      const s = typeof l.source === "string" ? l.source : (l.source as D3Node).id;
      const t = typeof l.target === "string" ? l.target : (l.target as D3Node).id;
      adj.get(s)?.add(t);
      adj.get(t)?.add(s);
    }
    neighborsMapRef.current = adj;

    // Custom force: 드래그 중인 노드의 1-hop 이웃을 끌어당김 (묶음 이동 효과)
    // 일반 link force 보다 훨씬 강한 spring 으로 이웃들이 잡은 노드를 따라옴.
    function dragAttract(alpha: number) {
      const dragId = dragNodeIdRef.current;
      if (!dragId) return;
      const nodes = d3NodesRef.current;
      const dragNode = nodes.find((n) => n.id === dragId);
      if (!dragNode) return;
      const neighbors = neighborsMapRef.current.get(dragId);
      if (!neighbors || neighbors.size === 0) return;

      const targetX = dragNode.fx ?? dragNode.x ?? 0;
      const targetY = dragNode.fy ?? dragNode.y ?? 0;
      const TARGET_DIST = 160;   // 이상적 이웃 거리
      const SPRING_K = 0.12;     // spring 강도 (낮춤: 0.25 → 0.12, 오버슈트/둥둥 방지)
      const MAX_DV = 6;          // tick 당 추가 속도 상한 (둥둥 떠오르는 방향 momentum 차단)

      for (const nid of neighbors) {
        const n = nodes.find((x) => x.id === nid);
        if (!n || n.fx != null) continue; // 고정 노드는 skip
        const dx = targetX - (n.x ?? 0);
        const dy = targetY - (n.y ?? 0);
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        // dist 가 TARGET_DIST 보다 멀면 +(끌어당김), 가까우면 -(밀어냄 약하게)
        const k = (dist - TARGET_DIST) * SPRING_K * alpha;
        let dvx = (dx / dist) * k;
        let dvy = (dy / dist) * k;
        // 속도 가산량 clamp — momentum 누적 방지
        if (dvx > MAX_DV) dvx = MAX_DV;
        else if (dvx < -MAX_DV) dvx = -MAX_DV;
        if (dvy > MAX_DV) dvy = MAX_DV;
        else if (dvy < -MAX_DV) dvy = -MAX_DV;
        n.vx = (n.vx ?? 0) + dvx;
        n.vy = (n.vy ?? 0) + dvy;
      }
    }

    const sim = forceSimulation<D3Node>(d3Nodes)
      .force(
        "link",
        forceLink<D3Node, SimulationLinkDatum<D3Node>>(d3Links)
          .id((d) => d.id)
          // 엣지 타입별 strength — 오라클/프로토콜 연결은 강하게
          .strength((l) => {
            const t = (l as SimulationLinkDatum<D3Node> & { etype?: string }).etype ?? "";
            return EDGE_STRENGTH[t] ?? DEFAULT_EDGE_STRENGTH;
          })
          // 엣지 타입별 목표 거리 — 강한 link 는 더 짧게
          .distance((l) => {
            const t = (l as SimulationLinkDatum<D3Node> & { etype?: string }).etype ?? "";
            return EDGE_DISTANCE[t] ?? DEFAULT_EDGE_DISTANCE;
          }),
      )
      // 노드 크기별 charge (인프라는 강하게 밀어냄, 작은 노드는 약하게)
      .force("charge", forceManyBody<D3Node>().strength((d) => getNodeCharge(d.id)))
      // 충돌 반경도 노드 크기 비례
      .force("collide", forceCollide<D3Node>((d) => getNodeRadius(d.id)))
      // Custom: 드래그 중인 노드 + 1-hop 이웃을 끌어당기는 spring
      .force("dragAttract", dragAttract)
      // 각 노드를 원래 레이아웃 좌표(home)로 살짝 끌어당김 — 둥둥 뜨는 drift 방지.
      // 강도가 낮아 드래그 추종은 그대로, 단지 momentum 누적이 home 쪽으로 상쇄됨.
      .force("anchorX", forceX<D3Node>((d) => d.homeX).strength(0.035))
      .force("anchorY", forceY<D3Node>((d) => d.homeY).strength(0.035))
      // 고무줄(spring) 효과 — 마찰 살짝 강화 (0.4 → 0.5) 로 오버슈트/둥둥 억제
      .alphaDecay(0.025)
      .velocityDecay(0.5);

    // Run ticks silently to get initial stable layout.
    // 350 ticks: 차등 force 가 평형에 도달할 시간 (200 → 350)
    sim.tick(350);

    // Apply initial d3 positions to ReactFlow nodes
    setNodes((nds) =>
      nds.map((n) => {
        const d3n = d3Nodes.find((d) => d.id === n.id);
        if (!d3n) return n;
        return { ...n, position: { x: d3n.x ?? n.position.x, y: d3n.y ?? n.position.y } };
      }),
    );

    // Stop after initial layout
    sim.stop();
    simRef.current = sim;

    return () => {
      sim.stop();
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [topology, setNodes]);

  // selectedNodeId 의 1-hop 이웃 ID 셋 (노드 확장에 사용)
  const expandedAroundSelected = useMemo<Set<string>>(() => {
    if (!selectedNodeId) return new Set();
    const out = new Set<string>([selectedNodeId]);
    for (const e of topology.edges) {
      if (e.source === selectedNodeId) out.add(e.target);
      if (e.target === selectedNodeId) out.add(e.source);
    }
    return out;
  }, [selectedNodeId, topology.edges]);

  // Sync nodeStates + walletHighlight + 포커스 줌 모드(hidden) + 확장(expanded) 으로 ReactFlow nodes 업데이트
  useEffect(() => {
    const highlightActive = (walletHighlightIds?.size ?? 0) > 0;
    const focusActive = !!focusOnlyIds && focusOnlyIds.size > 0;
    setNodes((nds) =>
      nds.map((n) => {
        const isHighlighted = walletHighlightIds?.has(n.id) ?? false;
        const isInFocus = focusActive ? (focusOnlyIds!.has(n.id)) : true;
        // 확장 조건: selected || selected의 이웃 || walletHighlight (focus center+related)
        const isExpanded =
          n.id === selectedNodeId ||
          expandedAroundSelected.has(n.id) ||
          isHighlighted;
        return {
          ...n,
          selected: n.id === selectedNodeId,
          // 포커스 줌 모드: 포커스 셋에 포함된 노드만 보이게
          hidden: focusActive && !isInFocus,
          data: {
            ...n.data,
            state: nodeStates[n.id] ?? SAFE_NODE_STATE,
            walletHighlight: isHighlighted,
            expanded: isExpanded,
            // 일반 페이드 (포커스 줌 모드에선 hidden 으로 처리되므로 적용 X)
            faded: !focusActive && highlightActive && !isHighlighted,
          },
        };
      }),
    );
    setEdges((eds) =>
      eds.map((e) => {
        const s = SEVERITY[(nodeStates[e.source] ?? SAFE_NODE_STATE).riskLevel];
        const t = SEVERITY[(nodeStates[e.target] ?? SAFE_NODE_STATE).riskLevel];
        const minSev = Math.min(s, t);
        // 엣지도 포커스 줌 모드에선 양쪽 노드가 모두 보이는 경우만 표시
        const edgeHidden = focusActive
          ? !(focusOnlyIds!.has(e.source) && focusOnlyIds!.has(e.target))
          : false;
        return {
          ...e,
          hidden: edgeHidden,
          data: {
            ...e.data,
            edgeType: e.data?.edgeType ?? "",
            active: minSev >= 1,
            danger: minSev >= 2,
          },
        };
      }),
    );
  }, [nodeStates, walletHighlightIds, focusOnlyIds, selectedNodeId, expandedAroundSelected, setNodes, setEdges]);

  // 포커스 줌 모드 진입/해제 시 자동 fitView (보이는 노드들만)
  useEffect(() => {
    if (!nodesInitializedRef.current) return;
    const t = setTimeout(() => {
      try {
        fitView({ padding: 0.18, duration: 500 });
      } catch {
        /* ignore */
      }
    }, 60);
    return () => clearTimeout(t);
    // focusOnlyIds 참조가 변할 때만 트리거
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusOnlyIds]);

  // Fit view on mount
  const nodesInitialized = useNodesInitialized();
  const { fitView, setCenter, getNode } = useReactFlow();
  const nodesInitializedRef = useRef(false);
  useEffect(() => {
    if (nodesInitialized) {
      nodesInitializedRef.current = true;
      fitView({ padding: 0.12, duration: 400 });
    }
  }, [nodesInitialized, fitView]);

  // Phase 4: focusCenterIds 변경 시 카메라 부드럽게 이동
  useEffect(() => {
    if (!focusCenterIds || focusCenterIds.length === 0) return;
    if (!nodesInitialized) return;

    // 첫 번째 center 노드를 카메라 중심으로
    const centerId = focusCenterIds[0];
    const node = getNode(centerId);
    if (node && node.position) {
      // ReactFlow Node 위치는 좌상단 — 노드 중심으로 보정 (대략 95×40)
      setCenter(node.position.x + 95, node.position.y + 40, {
        zoom: 1.0,
        duration: 600,
      });
    }
  }, [focusCenterIds, nodesInitialized, setCenter, getNode]);

  // 전염 애니메이션: 라운드가 바뀔 때마다 카메라가 "활성(전파된) 노드 영역"을 따라가게.
  // 라운드0 = 시작 노드 근처, 이후 프론티어가 퍼지면 화면도 확장돼 흐름을 따라감.
  useEffect(() => {
    if (!cameraFollow || !nodesInitializedRef.current) return;
    const activeIds = Object.entries(nodeStates)
      .filter(([, s]) => s && s.riskLevel !== "safe")
      .map(([id]) => ({ id }));
    if (activeIds.length === 0) return;
    const t = setTimeout(() => {
      try {
        fitView({ nodes: activeIds, padding: 0.4, duration: 700, maxZoom: 1.15, minZoom: 0.06 });
      } catch {
        /* ignore */
      }
    }, 60);
    return () => clearTimeout(t);
  }, [nodeStates, cameraFollow, fitView]);

  // 사용자가 노드를 직접 클릭(selectedNodeId 변경)하면 그 노드로 줌인.
  // focusCenterIds 와 별개로 selected 노드를 따라가게.
  useEffect(() => {
    if (!selectedNodeId || !nodesInitialized) return;
    const node = getNode(selectedNodeId);
    if (node && node.position) {
      setCenter(node.position.x + 95, node.position.y + 40, {
        zoom: 1.5,
        duration: 500,
      });
    }
  }, [selectedNodeId, nodesInitialized, setCenter, getNode]);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const onResize = () => {
      clearTimeout(timer);
      timer = setTimeout(() => fitView({ padding: 0.12, duration: 200 }), 140);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      clearTimeout(timer);
    };
  }, [fitView]);

  // 드래그 시작 — 모든 노드의 fx/fy 해제 (이전 잡았던 것 자유롭게) +
  // 현재 잡은 노드만 고정 시작.
  // 결과: 항상 "지금 잡고 있는 노드 하나"만 고정 위치, 나머지는 자유.
  const onNodeDragStart = useCallback<OnNodeDrag<RiskNodeType>>(
    (_, node) => {
      // 모든 노드의 fx/fy 해제
      for (const d of d3NodesRef.current) {
        if (d.id !== node.id) {
          d.fx = null;
          d.fy = null;
        }
      }
      // 잡은 노드만 고정
      const d3n = d3NodesRef.current.find((d) => d.id === node.id);
      if (d3n) {
        d3n.fx = node.position.x;
        d3n.fy = node.position.y;
      }
      dragNodeIdRef.current = node.id;
    },
    [],
  );

  // 드래그 중 — 잡은 노드 fx/fy 업데이트 + alpha 재충전 (이웃 따라옴)
  const onNodeDrag = useCallback<OnNodeDrag<RiskNodeType>>(
    (_, node) => {
      const sim = simRef.current;
      if (!sim) return;
      const d3n = d3NodesRef.current.find((d) => d.id === node.id);
      if (!d3n) return;
      d3n.fx = node.position.x;
      d3n.fy = node.position.y;

      // alpha 재충전 → 매 프레임 link force + dragAttract 작동
      if ((sim.alpha() ?? 0) < 0.2) {
        sim.alpha(0.3).restart();
      }

      // 1 tick 실행 후 React 노드 위치 sync (잡은 노드는 React 가 처리하므로 skip)
      sim.tick();
      setNodes((nds) =>
        nds.map((n) => {
          if (n.id === node.id) return n;
          const d = d3NodesRef.current.find((x) => x.id === n.id);
          if (!d) return n;
          return { ...n, position: { x: d.x ?? n.position.x, y: d.y ?? n.position.y } };
        }),
      );
    },
    [setNodes],
  );

  // 드래그 종료 — 잡은 노드도 fx/fy 해제 → 모든 노드가 자유.
  // 다음 드래그 시작 시까지 그래프는 자유 평형. 출렁이지 않도록 부드럽게 정착.
  const onNodeDragStop = useCallback<OnNodeDrag<RiskNodeType>>(
    (_, node) => {
      const sim = simRef.current;
      if (!sim) return;
      const d3n = d3NodesRef.current.find((d) => d.id === node.id);
      if (!d3n) return;

      // 잡은 노드도 해제 (이제 자유)
      d3n.fx = null;
      d3n.fy = null;
      dragNodeIdRef.current = null;

      // 마지막 위치 근처에서 부드럽게 평형 — alpha 낮게 + 짧은 ticks
      // (alpha 0.3, 120 ticks ≈ 2초). 출렁임 적게.
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      simRef.current.alpha(0.3).restart();

      let ticks = 0;
      const MAX_TICKS = 120;

      const tick = () => {
        if (!simRef.current) return;
        simRef.current.tick();
        ticks++;

        setNodes((nds) =>
          nds.map((n) => {
            const d = d3NodesRef.current.find((x) => x.id === n.id);
            if (!d) return n;
            return { ...n, position: { x: d.x ?? n.position.x, y: d.y ?? n.position.y } };
          }),
        );

        if (ticks < MAX_TICKS && (simRef.current?.alpha() ?? 0) > 0.001) {
          animFrameRef.current = requestAnimationFrame(tick);
        } else {
          simRef.current?.stop();
        }
      };

      animFrameRef.current = requestAnimationFrame(tick);
    },
    [setNodes],
  );

  const onNodeClick = useCallback<NodeMouseHandler>(
    (_, node) => onSelectNode(node.id),
    [onSelectNode],
  );

  // 빈 영역 클릭 — 선택 해제 + 모든 고정 노드 해제 (자유 배치로 복귀)
  const onPaneClick = useCallback(() => {
    onSelectNode(null);
    // 모든 d3 노드의 fx/fy 해제
    for (const d of d3NodesRef.current) {
      d.fx = null;
      d.fy = null;
    }
    // 약한 alpha 로 잠깐만 평형 재정착 (출렁임 적게)
    if (simRef.current) {
      simRef.current.alpha(0.3).restart();
      let ticks = 0;
      const tick = () => {
        if (!simRef.current) return;
        simRef.current.tick();
        ticks++;
        setNodes((nds) =>
          nds.map((n) => {
            const d = d3NodesRef.current.find((x) => x.id === n.id);
            if (!d || d.fx != null) return n;
            return { ...n, position: { x: d.x ?? n.position.x, y: d.y ?? n.position.y } };
          }),
        );
        if (ticks < 100 && (simRef.current?.alpha() ?? 0) > 0.001) {
          animFrameRef.current = requestAnimationFrame(tick);
        } else {
          simRef.current?.stop();
        }
      };
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = requestAnimationFrame(tick);
    }
  }, [onSelectNode, setNodes]);

  return (
    <ReactFlow<RiskNodeType, FloatingEdgeType>
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onNodeDragStart={onNodeDragStart}
        onNodeDrag={onNodeDrag}
        onNodeDragStop={onNodeDragStop}
        colorMode="dark"
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.05}
        maxZoom={2}
        nodesDraggable
        proOptions={{ hideAttribution: false }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#26262d" />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => {
            const state = nodeStates[(n as RiskNodeType).id];
            if (!state) return "#26262d";
            return state.riskLevel === "danger"
              ? "var(--color-danger)"
              : state.riskLevel === "caution"
                ? "var(--color-caution)"
                : "#33333a";
          }}
          maskColor="rgba(10,10,11,0.7)"
          style={{
            background: "rgba(19,19,22,0.75)",
            backdropFilter: "blur(8px)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: 8,
          }}
        />
      </ReactFlow>
  );
}
