import { useState } from "react";

import { useAuth } from "../store/auth";
import { cn } from "../lib/utils";
import { PageHeader } from "../components/ui";
import { AssetsOverview } from "../components/assets/AssetsOverview";
import { InvestmentsTab } from "../components/assets/InvestmentsTab";
import { LoansTab } from "../components/assets/LoansTab";
import { RatesCard } from "../components/assets/RatesCard";

type Tab = "overview" | "investments" | "loans" | "rates";

const TABS: { value: Tab; label: string }[] = [
  { value: "overview", label: "总览" },
  { value: "investments", label: "投资" },
  { value: "loans", label: "贷款" },
  { value: "rates", label: "汇率" },
];

export function AssetsPage() {
  const household = useAuth((state) => state.household);
  const [tab, setTab] = useState<Tab>("overview");
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
            onClick={() => setTab(item.value)}
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
      {tab === "investments" ? <InvestmentsTab /> : null}
      {tab === "loans" ? <LoansTab /> : null}
      {tab === "rates" ? <RatesCard /> : null}
    </div>
  );
}
