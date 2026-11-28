import { useNavigate, useSearch } from "@tanstack/react-router";

import { useAuth } from "../store/auth";
import { cn } from "../lib/utils";
import type { AssetsTab } from "../router";
import { PageHeader } from "../components/ui";
import { AssetsOverview } from "../components/assets/AssetsOverview";
import { InvestmentsTab } from "../components/assets/InvestmentsTab";
import { LoansTab } from "../components/assets/LoansTab";
import { RatesCard } from "../components/assets/RatesCard";

const TABS: { value: AssetsTab; label: string }[] = [
  { value: "overview", label: "总览" },
  { value: "investments", label: "投资" },
  { value: "loans", label: "贷款" },
  { value: "rates", label: "汇率" },
];

export function AssetsPage() {
  const household = useAuth((state) => state.household);
  const navigate = useNavigate({ from: "/assets" });
  const search = useSearch({ from: "/app/assets" });
  const tab: AssetsTab = search.tab ?? "overview";
  const base = household?.base_currency ?? "CNY";

  return (
    <div>
      <PageHeader
        eyebrow="Assets"
        title="资产负债"
        description="净资产、投资持股、贷款负债与汇率 —— 每日快照留住你的财富曲线。"
      />

      <div className="mb-4 flex flex-wrap gap-1 rounded-2xl border border-slate-200 bg-white p-1 shadow-sm">
        {TABS.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() =>
              navigate({
                search: item.value === "overview" ? {} : { tab: item.value },
                replace: true,
              })
            }
            className={cn(
              "flex-1 rounded-xl px-4 py-2 text-sm font-medium transition",
              tab === item.value
                ? "bg-primary-600 text-white shadow-sm"
                : "text-slate-600 hover:bg-slate-50",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "overview" ? <AssetsOverview base={base} /> : null}
      {tab === "investments" ? <InvestmentsTab initialExpandedId={search.investment} /> : null}
      {tab === "loans" ? <LoansTab /> : null}
      {tab === "rates" ? <RatesCard /> : null}
    </div>
  );
}
