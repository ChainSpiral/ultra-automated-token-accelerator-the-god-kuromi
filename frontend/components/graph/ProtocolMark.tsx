"use client";

import { useState } from "react";

import type { ProtocolBrand } from "./protocols";
import { cn } from "@/lib/utils";

interface Props {
  brand: ProtocolBrand;
  /** tailwind size class for the box, e.g. "size-9" */
  boxClass: string;
  /** monogram font px */
  fontPx: number;
}

/**
 * Renders a protocol's logo, trying sources in order and falling back gracefully:
 *   1. /protocols/<slug>.svg   — a local file the user can drop in (highest priority)
 *   2. DefiLlama icon CDN       — the real protocol logo, fetched live
 *   3. brand-coloured monogram  — always works, so identity is never lost
 */
export function ProtocolMark({ brand, boxClass, fontPx }: Props) {
  const sources = [
    `/protocols/${brand.slug}.svg`,
    brand.llama ? `https://icons.llamao.fi/icons/protocols/${brand.llama}?w=48&h=48` : null,
  ].filter(Boolean) as string[];

  const [idx, setIdx] = useState(0);
  const exhausted = idx >= sources.length;

  return (
    <div
      className={cn("flex shrink-0 items-center justify-center overflow-hidden rounded-lg", boxClass)}
      style={{ backgroundColor: `${brand.color}22` }}
      title={brand.label}
    >
      {!exhausted ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={sources[idx]}
          alt={brand.label}
          className="size-full object-contain p-0.5"
          onError={() => setIdx((i) => i + 1)}
        />
      ) : (
        <span
          className="font-bold leading-none"
          style={{ color: brand.color, fontSize: fontPx }}
        >
          {brand.mark}
        </span>
      )}
    </div>
  );
}
