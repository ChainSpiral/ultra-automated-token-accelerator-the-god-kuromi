"use client";

import {
  type Edge,
  type EdgeProps,
  getBezierPath,
  useInternalNode,
} from "@xyflow/react";

import { getEdgeParams } from "@/lib/floating-edge";

export interface FloatingEdgeData extends Record<string, unknown> {
  edgeType: string;
  active: boolean;
  danger: boolean;
  /** cross-protocol bridge tier: potential | latent | realized */
  tier?: string;
  bridge?: boolean;
  sharedWhales?: number;
}

export type FloatingEdgeType = Edge<FloatingEdgeData, "floating">;

export function FloatingEdge({
  source,
  target,
  markerEnd,
  data,
}: EdgeProps<FloatingEdgeType>) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);

  if (!sourceNode || !targetNode) return null;

  const { sx, sy, tx, ty, sourcePos, targetPos } = getEdgeParams(
    sourceNode,
    targetNode,
  );

  const [path] = getBezierPath({
    sourceX: sx,
    sourceY: sy,
    sourcePosition: sourcePos,
    targetPosition: targetPos,
    targetX: tx,
    targetY: ty,
  });

  const active = data?.active ?? false;
  const danger = data?.danger ?? false;

  const stroke = danger
    ? "var(--color-danger)"
    : active
      ? "var(--color-caution)"
      : "var(--color-border-strong)";

  return (
    <path
      d={path}
      fill="none"
      stroke={stroke}
      strokeWidth={active || danger ? 2 : 1.25}
      strokeOpacity={active || danger ? 0.9 : 0.55}
      markerEnd={markerEnd}
      style={{
        transition: "stroke 600ms var(--ease-snappy), stroke-opacity 600ms",
      }}
    />
  );
}
