import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowDownLeft, ArrowUpRight, Landmark, Scale, TrendingUp, Wallet } from "lucide-react";

import { ApiError } from "../api/client";
import { assetsApi, statisticsApi, transactionsApi } from "../api/endpoints";
import type { Transaction } from "../api/types";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  PageHeader,
  Spinner,
} from "../components/ui";
import { useAccountNames, useCategoryNames } from "../hooks/useReference";
import { errorMessage, formatDate, money } from "../lib/utils";
import { useAuth } from "../store/auth";

export function DashboardPage() {
  const household = useAuth((state) => state.household);
  const user = useAuth((state) => state.user);
  const accountNames = useAccountNames();
  const categoryNames = useCategoryNames();

  const overview = useQuery({
    queryKey: ["statistics", "overview"],
    queryFn: () => statisticsApi.overview(),
  });
  const balances = useQuery({
    queryKey: ["statistics", "account-balances"],
    queryFn: statisticsApi.accountBalances,
  });
  const recent = useQuery({
    queryKey: ["transactions", "recent"],
    queryFn: () =>
      transactionsApi.list({ page_size: 6, sort_by: "transaction_date", sort_order: "desc" }),
  });

  const base = overview.data?.base_currency ?? household?.base_currency ?? "CNY";

  return (
    <div>
      <PageHeader
        eyebrow="Dashboard"
        title={`你好，${user?.display_name ?? user?.username ?? "家庭成员"}`}
        description={`${household?.name ?? "我的家庭"} · 数据截至 ${formatDate(
          new Date().toISOString(),
        )}`}
        action={
          <Link
            to="/transactions"
            className="inline-flex items-center gap-2 rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-primary-700"
          >
            <TrendingUp className="h-4 w-4" />
            记一笔
          </Link>
        }
      />

      {overview.isError ? (
        <ErrorBanner message={errorMessage(overview.error)} />
      ) : overview.isLoading ? (
        <Spinner />
      ) : overview.data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="本月收入"
            value={money(overview.data.income, base)}
            hint={`${overview.data.income_count} 笔`}
            icon={ArrowDownLeft}
            tone="text-primary-700 bg-primary-50"
          />
          <MetricCard
            label="本月支出"
            value={money(overview.data.expense, base)}
            hint={`${overview.data.expense_count} 笔`}
            icon={ArrowUpRight}
            tone="text-red-700 bg-red-50"
          />
          <MetricCard
            label="本月结余"
            value={money(overview.data.net, base)}
            hint="收入 - 支出（本位币）"
            icon={Scale}
            tone="text-blue-700 bg-blue-50"
          />
          <MetricCard
            label="账户数"
            value={String(overview.data.account_count)}
            hint="包含所有启用账户"
            icon={Wallet}
            tone="text-amber-700 bg-amber-50"
          />
        </div>
      ) : null}

      <NetWorthStrip base={base} />

      <div className="mt-6 grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader
            title="最近记录"
            description="按交易时间倒序"
            action={
              <Link to="/transactions" className="text-xs font-medium text-primary-700">
                查看全部 →
              </Link>
            }
          />
          {recent.isLoading ? (
            <Spinner />
          ) : recent.isError ? (
            <div className="p-5">
              <ErrorBanner message={errorMessage(recent.error)} />
            </div>
          ) : recent.data && recent.data.items.length ? (
            <ul className="divide-y divide-ink/6">
              {recent.data.items.map((item) => (
                <TransactionRow
                  key={item.id}
                  transaction={item}
                  accountName={accountNames.names.get(item.account_id) ?? "账户"}
                  categoryName={
                    item.category_id ? categoryNames.names.get(item.category_id) : undefined
                  }
                />
              ))}
            </ul>
          ) : (
            <EmptyState
              title="还没有收支记录"
              description="先创建账户，然后记录第一笔收入或支出。"
            />
          )}
        </Card>

        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title="资产分布" description="按各账户记账币种汇总" />
            {balances.isLoading ? (
              <Spinner />
            ) : balances.isError ? (
              <div className="p-5">
                <ErrorBanner message={errorMessage(balances.error)} />
              </div>
            ) : balances.data && balances.data.balances.length ? (
              <ul className="divide-y divide-ink/6">
                {balances.data.balances.map((item) => (
                  <li key={item.currency} className="flex items-center justify-between px-5 py-3.5">
                    <span className="flex items-center gap-2 text-sm text-ink/70">
                      <Landmark className="h-4 w-4 text-ink/35" />
                      {item.currency}
                    </span>
                    <span className="text-sm font-medium text-ink">
                      {money(item.book_balance, item.currency)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="暂无账户余额" description="创建账户并设置期初余额后显示。" />
            )}
          </Card>

          <Card className="p-5">
            <h2 className="text-sm font-semibold text-ink">快速入口</h2>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <QuickLink to="/imports" label="导入账单" />
              <QuickLink to="/statistics" label="月度统计" />
              <QuickLink to="/accounts" label="管理账户" />
              <QuickLink to="/categories" label="维护分类" />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  icon: typeof Wallet;
  tone: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-ink/45">{label}</p>
          <p className="mt-2 text-lg font-semibold tracking-tight text-ink">{value}</p>
          <p className="mt-1 text-xs text-ink/40">{hint}</p>
        </div>
        <span className={`grid h-9 w-9 place-items-center rounded-xl ${tone}`}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
    </Card>
  );
}

function TransactionRow({
  transaction,
  accountName,
  categoryName,
}: {
  transaction: Transaction;
  accountName: string;
  categoryName?: string;
}) {
  const isIncome = transaction.transaction_type === "income";
  const isOpening = transaction.transaction_type === "opening_balance";
  return (
    <li className="flex items-center justify-between gap-3 px-5 py-3.5">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-ink">
          {transaction.description || categoryName || (isOpening ? "期初余额" : "未命名记录")}
        </p>
        <p className="mt-0.5 truncate text-xs text-ink/45">
          {formatDate(transaction.transaction_date)} · {accountName}
          {categoryName && transaction.description ? ` · ${categoryName}` : ""}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span
          className={`text-sm font-semibold ${
            isOpening ? "text-blue-700" : isIncome ? "text-primary-700" : "text-red-600"
          }`}
        >
          {isOpening ? "" : isIncome ? "+" : "−"}
          {money(transaction.amount, transaction.currency)}
        </span>
        {transaction.status !== "confirmed" ? (
          <Badge tone={transaction.status === "draft" ? "amber" : "slate"}>
            {transaction.status === "draft" ? "草稿" : "已冲销"}
          </Badge>
        ) : null}
      </div>
    </li>
  );
}

function QuickLink({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      className="rounded-xl border border-ink/10 bg-white px-3 py-2.5 text-center text-xs font-medium text-ink/65 transition hover:border-primary-300 hover:text-primary-700"
    >
      {label}
    </Link>
  );
}

function NetWorthStrip({ base }: { base: string }) {
  const queryClient = useQueryClient();
  const summary = useQuery({
    queryKey: ["assets", "summary"],
    queryFn: assetsApi.summary,
    retry: false,
  });
  const recordSnapshot = useMutation({
    mutationFn: assetsApi.createSnapshot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
  });

  const error = summary.error;
  if (error instanceof ApiError && error.code === "EXCHANGE_RATE_NOT_FOUND") {
    return (
      <Card className="mt-6 border-amber-200 bg-amber-50 p-4">
        <p className="text-sm text-amber-800">
          净资产暂无法折算：缺少汇率。前往{" "}
          <Link to="/assets" className="font-medium underline">
            资产负债 · 汇率
          </Link>{" "}
          补录缺失币对后即可查看。
        </p>
      </Card>
    );
  }
  if (!summary.data) return null;

  const maturedCount = summary.data.matured_investments.length;

  return (
    <Card className="mt-6 flex flex-wrap items-center gap-4 p-4">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-ink/45">家庭净资产</p>
        <p className="mt-1 text-2xl font-semibold tracking-tight text-ink">
          {money(summary.data.net_worth, base)}
        </p>
        <p className="mt-1 text-xs text-ink/40">
          闲置 {money(summary.data.buckets.idle, base)} · 理财中{" "}
          {money(summary.data.buckets.invested, base)} · 负债 {money(summary.data.total_liabilities, base)}
          {maturedCount > 0 ? ` · ${maturedCount} 笔已到期未赎回` : ""}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm text-slate-700 transition hover:border-slate-300 disabled:opacity-50"
          disabled={recordSnapshot.isPending}
          onClick={() => recordSnapshot.mutate()}
        >
          {recordSnapshot.isPending ? "记录中…" : "记录今日快照"}
        </button>
        <Link
          to="/assets"
          className="rounded-xl bg-primary-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-primary-700"
        >
          查看资产负债 →
        </Link>
      </div>
    </Card>
  );
}
