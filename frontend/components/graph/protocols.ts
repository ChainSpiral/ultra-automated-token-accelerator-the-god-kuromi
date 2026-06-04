/**
 * Protocol brand registry — so a graph node can show WHICH protocol it belongs to.
 *
 * Two resolvers:
 *  - fromVenue(): pool-owning protocol of a lending-market node (Morpho/Aave/Spark…),
 *    fed by the backend `metadata.venue` tag.
 *  - fromSymbol(): the issuer of a collateral token (wstETH→Lido, ezETH→Renzo, PT-*→Pendle).
 *
 * Each brand has a `slug`. The <ProtocolMark> renders `/protocols/<slug>.svg` if that
 * file exists (drop real logo files into frontend/public/protocols/), otherwise a clean
 * brand-coloured monogram. So identity is ALWAYS clear; real logos are an easy upgrade.
 */

export interface ProtocolBrand {
  slug: string;
  label: string;
  color: string;
  /** monogram shown when no logo image is present (1–2 chars) */
  mark: string;
  /** DefiLlama protocol slug — used to fetch the real logo from their icon CDN */
  llama?: string;
}

export const PROTOCOLS: Record<string, ProtocolBrand> = {
  morpho:     { slug: "morpho",     label: "Morpho Blue", color: "#2470FF", mark: "M",  llama: "morpho-blue" },
  aave:       { slug: "aave",       label: "Aave V3",     color: "#9896FF", mark: "Aa", llama: "aave-v3" },
  spark:      { slug: "spark",      label: "Spark",       color: "#F5A623", mark: "Sp", llama: "spark" },
  pendle:     { slug: "pendle",     label: "Pendle",      color: "#1AAB9B", mark: "Pe", llama: "pendle" },
  lido:       { slug: "lido",       label: "Lido",        color: "#00A3FF", mark: "Li", llama: "lido" },
  etherfi:    { slug: "etherfi",    label: "ether.fi",    color: "#6F7BF7", mark: "eF", llama: "ether.fi" },
  renzo:      { slug: "renzo",      label: "Renzo",       color: "#A855F7", mark: "Re", llama: "renzo" },
  kelp:       { slug: "kelp",       label: "Kelp",        color: "#8FD613", mark: "Ke", llama: "kelp-dao" },
  rocketpool: { slug: "rocketpool", label: "Rocket Pool", color: "#FF7324", mark: "rP", llama: "rocket-pool" },
  coinbase:   { slug: "coinbase",   label: "Coinbase",    color: "#0052FF", mark: "cb" },
  sky:        { slug: "sky",        label: "Sky",         color: "#1AAB9B", mark: "Sk", llama: "sky-lending" },
  frax:       { slug: "frax",       label: "Frax",        color: "#111111", mark: "Fx", llama: "frax" },
  stader:     { slug: "stader",     label: "Stader",      color: "#07C8F9", mark: "St", llama: "stader" },
  mantle:     { slug: "mantle",     label: "Mantle",      color: "#65B3AE", mark: "mE", llama: "mantle-staked-eth" },
};

/** Pool-owning protocol from a backend venue tag. */
export function brandFromVenue(venue?: string | null): ProtocolBrand | null {
  if (!venue) return null;
  const v = venue.toLowerCase();
  if (v.includes("morpho")) return PROTOCOLS.morpho;
  if (v.includes("spark")) return PROTOCOLS.spark;
  if (v.includes("aave")) return PROTOCOLS.aave;
  if (v.includes("pendle")) return PROTOCOLS.pendle;
  if (v.includes("sky")) return PROTOCOLS.sky;
  return null;
}

/** Issuer of a collateral token, from its symbol. */
export function brandFromSymbol(symbol?: string | null): ProtocolBrand | null {
  if (!symbol) return null;
  const s = symbol.toLowerCase();
  if (s.startsWith("pt-") || s.startsWith("pt_")) return PROTOCOLS.pendle;
  if (s === "wsteth" || s === "steth") return PROTOCOLS.lido;
  if (s === "weeth" || s === "eeth" || s === "weeths") return PROTOCOLS.etherfi;
  if (s === "ezeth") return PROTOCOLS.renzo;
  if (s === "rseth" || s === "wrseth") return PROTOCOLS.kelp;
  if (s === "reth") return PROTOCOLS.rocketpool;
  if (s === "cbeth" || s === "cbbtc") return PROTOCOLS.coinbase;
  if (s === "sfrxeth" || s === "frxeth") return PROTOCOLS.frax;
  if (s === "ethx") return PROTOCOLS.stader;
  if (s === "meth") return PROTOCOLS.mantle;
  return null;
}
