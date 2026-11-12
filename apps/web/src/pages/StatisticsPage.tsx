import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { statisticsApi } from "../api/endpoints";
import { Card, CardHeader, EmptyState, ErrorBanner, Field, Input, PageHeader, Spinner } from "../components/ui";
import { currentMonthRange, errorMessage, money } from "../lib/utils";
import { useAuth } from "../store/auth";

export function StatisticsPage() {
  const household = useAuth((state) => state.household);
  const initial = currentMonthRange();
  const [startDate, setStartDate] = useState(initial.start);
  const [endDate, setEndDate] = useState(initial.end);
  const [categoryType, setCategoryType] = useState<"expense" | "income">("expense");

  const overview = useQuery({
    queryKey: ["statistics", "overview", startDate, endDate],
    queryFn: () => statisticsApi.overview({ start_date: startDate, end_date: endDate }),
  });
  const monthly = useQuery({
    queryKey: ["statistics", "monthly", startDate, endDate],
    queryFn: () => statisticsApi.monthly({ start_date: startDate, end_date: endDate }),
  });
  const category = useQuery({
    queryKey: ["statistics", "category", startDate, endDate, categoryType],
    queryFn: () =>
      statisticsApi.category({
        start_date: startDate,
        end_date: endDate,
        transaction_type: categoryType,
      }),
  });

  const base = overview.data?.base_currency ?? household?.base_currency ?? "CNY";
  const maxPeriod = Math.max(
    1,
    ...(monthly.data?.items ?? []).map((item) =>
      Math.max(Number(item.income), Number(item.expense)),
    ),
  );
  const categoryTotal = Number(
    categoryType === "expense" ? category.data?.expense_total : category.data?.income_total,
  );

  return (
    <div>
      <PageHeader
        eyebrow="Statistics"
        title="统计"
        description="按本位币汇总；金额来源为账户记账金额换算后的 base_amount。"
      />

      <Card className="mb-4 p-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="开始日期">
            <Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
          </Field>
          <Field label="结束日期">
            <Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
          </Field>
          <div className="flex items-end gap-2">
            <button
              type="button"
              className="rounded-xl border border-ink/10 px-3 py-2 text-xs text-ink/60 hover:border-primary-300"
              onClick={() => {
                const range = currentMonthRange();
                setStartDate(range.start);
                setEndDate(range.end);
              }}
            >
              本月
            </button>
            <button
              type="button"
              className="rounded-xl border border-ink/10 px-3 py-2 text-xs text-ink/60 hover:border-primary-300"
              onClick={() => {
                const year = new Date().getFullYear();
                setStartDate(`${year}-01-01`);
                setEndDate(`${year}-12-31`);
              }}
            >
              本年
            </button>
          </div>
        </div>
      </Card>

      {overview.isError ? (
        <ErrorBanner message={errorMessage(overview.error)} />
      ) : overview.isLoading ? (
        <Spinner />
      ) : overview.data ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <Summary label="收入" value={money(overview.data.income, base)} tone="text-primary-700" />
          <Summary label="支出" value={money(overview.data.expense, base)} tone="text-red-600" />
          <Summary label="结余" value={money(overview.data.net, base)} tone="text-blue-700" />
        </div>
      ) : null}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="月度趋势" description="收入与支出对比" />
          {monthly.isLoading ? (
            <Spinner />
          ) : monthly.isError ? (
            <div className="p-5">
              <ErrorBanner message={errorMessage(monthly.error)} />
            </div>
          ) : monthly.data && monthly.data.items.length ? (
            <div className="space-y-3 p-5">
              {monthly.data.items.map((item) => (
                <div key={item.period}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="font-medium text-ink/70">{item.period}</span>
                    <span className="text-ink/45">
                      结余 {money(item.net, base)}
                    </span>
                  </div>
                  <div className="space-y-1">
                    <Bar value={Number(item.income)} max={maxPeriod} tone="bg-primary-500" />
                    <Bar value={Number(item.expense)} max={maxPeriod} tone="bg-red-400" />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="所选区间没有数据" description="调整日期范围或先记录收支。" />
          )}
        </Card>

        <Card>
          <CardHeader
            title="分类占比"
            description={categoryType === "expense" ? "支出分类" : "收入分类"}
            action={
              <div className="flex gap-1 rounded-full bg-ink/5 p-1 text-xs">
                {(["expense", "income"] as const).map((type) => (
                  <button
                    key={type}
                    type="button"
                    onClick={() => setCategoryType(type)}
                    className={`rounded-full px-3 py-1 ${
                      categoryType === type ? "bg-white text-ink shadow-sm" : "text-ink/45"
                    }`}
                  >
                    {type === "expense" ? "支出" : "收入"}
                  </button>
                ))}
              </div>
            }
          />
          {category.isLoading ? (
            <Spinner />
          ) : category.isError ? (
            <div className="p-5">
              <ErrorBanner message={errorMessage(category.error)} />
            </div>
          ) : category.data && category.data.items.length ? (
            <ul className="divide-y divide-ink/6">
              {category.data.items.map((item) => {
                const amount = Number(item.amount);
                const ratio = categoryTotal > 0 ? (amount / categoryTotal) * 100 : 0;
                return (
                  <li key={`${item.category_id ?? "none"}-${item.category_name}`} className="px-5 py-3">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-ink/75">{item.category_name}</span>
                      <span className="font-medium text-ink">{money(item.amount, base)}</span>
                    </div>
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink/8">
                        <div
                          className={`h-full rounded-full ${
                            categoryType === "expense" ? "bg-red-400" : "bg-primary-500"
                          }`}
                          style={{ width: `${Math.max(2, ratio)}%` }}
                        />
                      </div>
                      <span className="w-12 text-right text-xs text-ink/40">
                        {ratio.toFixed(1)}%
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState title="暂无分类统计" />
          )}
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader title="账户余额" description="按账户与币种列示账面余额" />
        <BalancesTable />
      </Card>
    </div>
  );
}

function Summary({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium text-ink/45">{label}</p>
      <p className={`mt-2 text-xl font-semibold tracking-tight ${tone}`}>{value}</p>
    </Card>
  );
}

function Bar({ value, max, tone }: { value: number; max: number; tone: string }) {
  const width = value > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="h-2 overflow-hidden rounded-full bg-ink/6">
      <div className={`h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
    </div>
  );
}

function BalancesTable() {
  const balances = useQuery({
    queryKey: ["statistics", "account-balances"],
    queryFn: statisticsApi.accountBalances,
  });

  if (balances.isLoading) return <Spinner />;
  if (balances.isError) {
    return (
      <div className="p-5">
        <ErrorBanner message={errorMessage(balances.error)} />
      </div>
    );
  }
  if (!balances.data?.accounts.length) {
    return <EmptyState title="暂无账户" description="创建账户后可查看余额分布。" />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead>
          <tr className="border-b border-ink/8 text-xs uppercase tracking-wide text-ink/40">
            <th className="px-5 py-3 font-medium">账户</th>
            <th className="px-3 py-3 font-medium">类型</th>
            <th className="px-3 py-3 font-medium">币种余额</th>
            <th className="px-5 py-3 text-right font-medium">状态</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink/6">
          {balances.data.accounts.map((account) => (
            <tr key={account.account_id}>
              <td className="px-5 py-3 font-medium text-ink">{account.name}</td>
              <td className="px-3 py-3 text-xs text-ink/50">{account.account_type}</td>
              <td className="px-3 py-3">
                {account.balances.length ? (
                  <ul className="space-y-0.5 text-xs">
                    {account.balances.map((line) => (
                      <li key={line.currency} className="flex gap-2">
                        <span className="w-10 text-ink/40">{line.currency}</span>
                        <span className="text-ink/80">{money(line.book_balance, line.currency)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-xs text-ink/35">—</span>
                )}
              </td>
              <td className="px-5 py-3 text-right text-xs text-ink/45">
                {account.is_active ? "启用" : "停用"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
