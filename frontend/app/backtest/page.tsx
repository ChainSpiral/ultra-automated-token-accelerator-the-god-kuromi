import { BacktestPage } from "@/components/backtest/BacktestPage";

// Backtest page renders HISTORICAL (past-incident) contagion graphs only — it must
// NOT show the live /api/graph mapping (that belongs to the simulation page).
// BacktestPage loads each incident's self-contained historical graph on its own.
export default function BacktestRoute() {
  return <BacktestPage />;
}
