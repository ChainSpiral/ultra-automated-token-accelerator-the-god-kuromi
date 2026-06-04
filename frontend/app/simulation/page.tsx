import { SimulationPage } from "@/components/simulation/SimulationPage";
import { SiteHeader } from "@/components/SiteHeader";
import { fetchGraph } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SimulationRoute() {
  let topology;
  try {
    topology = await fetchGraph();  // FULL ecosystem map (do not replace with the sparse overview)
  } catch {
    return (
      <div className="flex h-dvh flex-col">
        <SiteHeader />
        <div className="flex flex-1 items-center justify-center p-12">
          <div className="max-w-md space-y-3 text-center">
            <h2 className="text-lg font-semibold text-[var(--color-danger)]">
              백엔드에 연결하지 못했습니다
            </h2>
            <p className="text-sm text-[var(--color-text-secondary)]">
              simulator API 서버가 실행 중인지 확인하세요.
            </p>
            <pre className="overflow-x-auto rounded-lg bg-[var(--color-surface)] p-3 text-left font-mono text-xs text-[var(--color-text-muted)]">
              cd simulator{"\n"}uvicorn api.main:app --reload
            </pre>
          </div>
        </div>
      </div>
    );
  }

  return <SimulationPage topology={topology} />;
}
