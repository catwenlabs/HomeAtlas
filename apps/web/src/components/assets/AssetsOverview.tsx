import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AlertTriangle,
  CalendarClock,
  ChevronDown,
  Coins,
  Landmark,
  PiggyBank,
  Scale,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { assetsApi, investmentsApi, loansApi } from "../../api/endpoints";
import { money, pnlClass } from "../../lib/utils";
import { Card, CardHeader, EmptyState, ErrorBanner, Spinner } from "../ui";
import { StatCard } from "./StatCard";

const TYPE_COLORS = [
  "#4f46e5",
  "#0ea5e9",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#64748b",
];

const TYPE_LABELS: Record<string, string> = {
  fixed: "定期理财",
  daily: "活期理财",
  fund: "基金",
  cash: "现金管理",
  stock: "股票",
  bond: "债券",
  other: "其他",
};

export function AssetsOverview({ base }: { base: string }) {
  const queryClient = useQueryClient();
  const [guideOpen, setGuideOpen] = useState(false);

  const summary = useQuery({
    queryKey: ["assets", "summary"],
    queryFn: assetsApi.summary,
  });
  const snapshots = useQuery({
    queryKey: ["assets", "snapshots", "trend"],
    queryFn: () => assetsApi.snapshots(),
  });
  const loans = useQuery({
    queryKey: ["loans", "active"],
    queryFn: () => loansApi.list({ status: "active" }),
  });
  const investments = useQuery({
    queryKey: ["investments", "overview-allocation"],
    queryFn: () => investmentsApi.list(),
  });

  const recordSnapshot = useMutation({
    mutationFn: assetsApi.createSnapshot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
  });

  if (summary.isLoading) return <Spinner />;
  if (summary.isError) {
    const error = summary.error;
    if (error instanceof ApiError && error.code === "EXCHANGE_RATE_NOT_FOUND") {
      return (
        <Card className="border-amber-200 bg-amber-50 p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-600" />
            <div>
              <p className="font-medium text-amber-900">缺少汇率，暂无法折算净资产</p>
              <p className="mt-1 text-sm text-amber-800">
                请到「汇率」标签页补录缺失币对的最新价，然后回到这里查看总览。
              </p>
            </div>
          </div>
        </Card>
      );
    }
    return <ErrorBanner message={errorMessageOf(error)} />;
  }
  if (summary.data === undefined) return <Spinner />;

  const data = summary.data;
  const trendPoints = (snapshots.data?.items ?? [])
    .slice()
    .sort((a, b) => a.snapshot_date.localeCompare(b.snapshot_date))
    .map((item) => ({ date: item.snapshot_date.slice(5), net_worth: Number(item.net_worth) }));

  const allocation = Object.entries(
    (investments.data?.items ?? []).reduce<Record<string, number>>((acc, investment) => {
      if (investment.status !== "active") return acc;
      const value = Number(investment.principal);
      acc[investment.investment_type] = (acc[investment.investment_type] ?? 0) + value;
      return acc;
    }, {}),
  )
    .filter(([, value]) => value > 0)
    .map(([type, value]) => ({ name: TYPE_LABELS[type] ?? type, value }));

  const dueSoon = (loans.data?.items ?? [])
    .filter((loan) => loan.due_day !== null)
    .map((loan) => ({ loan, days: daysUntilDueDay(loan.due_day as number) }))
    .filter((entry) => entry.days !== null && entry.days <= 7)
    .sort((a, b) => (a.days ?? 0) - (b.days ?? 0));

  const hasReminders =
    (data.matured_investments.length > 0 || dueSoon.length > 0 || data.unmapped_cash !== "0E-8");

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="净资产"
          value={money(data.net_worth, base)}
          hint={`现金 + 投资账户 + 浮盈 − 负债 · ${data.currency_breakdown.length} 个币种`}
          icon={Scale}
          tone="text-indigo-700 bg-indigo-50"
        />
        <StatCard
          label="闲置现金"
          value={money(data.buckets.idle, base)}
          icon={Wallet}
          tone="text-sky-700 bg-sky-50"
        />
        <StatCard
          label="理财中"
          value={money(data.buckets.invested, base)}
          hint={`浮盈 ${money(data.unrealized_pnl, base)}`}
          hintTone={pnlClass(Number(data.unrealized_pnl))}
          icon={PiggyBank}
          tone="text-emerald-700 bg-emerald-50"
        />
        <StatCard
          label="总负债"
          value={money(data.total_liabilities, base)}
          hint={`日利息支出 ${money(data.daily_interest_expense, base)}`}
          icon={Landmark}
          tone="text-red-700 bg-red-50"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard
          label="已到期未赎回"
          value={money(data.buckets.matured, base)}
          hint={`${data.matured_investments.length} 笔 · 仍计入净资产`}
          icon={CalendarClock}
          tone="text-amber-700 bg-amber-50"
        />
        <StatCard
          label="日利息收入（估算）"
          value={money(data.daily_interest_income, base)}
          icon={TrendingUp}
          tone="text-emerald-700 bg-emerald-50"
        />
        <StatCard
          label="未映射现金（诊断）"
          value={money(data.unmapped_cash, base)}
          hint={data.unmapped_cash.startsWith("-") ? "本金未到位，建议核对入金" : "投资账户与登记本金差额"}
          icon={Coins}
          tone="text-slate-700 bg-slate-100"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <CardHeader
            title="净资产趋势"
            description={`${trendPoints.length} 天快照`}
            action={
              <button
                type="button"
                className="rounded-xl bg-primary-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50"
                disabled={recordSnapshot.isPending}
                onClick={() => recordSnapshot.mutate()}
              >
                {recordSnapshot.isPending ? "记录中…" : "记录今日快照"}
              </button>
            }
          />
          {recordSnapshot.isError ? (
            <ErrorBanner message={errorMessageOf(recordSnapshot.error)} />
          ) : null}
          {recordSnapshot.isSuccess ? (
            <p className="mt-2 text-xs text-emerald-700">已记录 {new Date().toLocaleDateString("zh-CN")} 的快照。</p>
          ) : null}
          <div className="mt-4">
            {trendPoints.length === 0 ? (
              <EmptyState
                title="还没有快照"
                description="点击「记录今日快照」保留今天的净资产；每天记录一次，趋势图就会生长。"
              />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={trendPoints} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                  <defs>
                    <linearGradient id="netWorthFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#4f46e5" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="#4f46e5" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                  <YAxis
                    tick={{ fontSize: 12 }}
                    tickLine={false}
                    axisLine={false}
                    width={72}
                    tickFormatter={(value: number) => compactNumber(value)}
                  />
                  <Tooltip
                    formatter={(value) => [money(Number(value), base), "净资产"]}
                    labelStyle={{ fontSize: 12 }}
                  />
                  <Area
                    type="monotone"
                    dataKey="net_worth"
                    stroke="#4f46e5"
                    strokeWidth={2}
                    fill="url(#netWorthFill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="p-5">
            <CardHeader title="资产配置" description="按投资类型（登记口径）" />
            {allocation.length === 0 ? (
              <EmptyState title="暂无在投资产" description="到「投资」标签页登记第一笔投资。" />
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={allocation}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={48}
                    outerRadius={76}
                    paddingAngle={2}
                  >
                    {allocation.map((entry, index) => (
                      <Cell key={entry.name} fill={TYPE_COLORS[index % TYPE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => money(Number(value), base)} />
                </PieChart>
              </ResponsiveContainer>
            )}
            <ul className="mt-2 space-y-1">
              {allocation.map((entry, index) => (
                <li key={entry.name} className="flex items-center justify-between text-xs text-slate-600">
                  <span className="flex items-center gap-1.5">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ backgroundColor: TYPE_COLORS[index % TYPE_COLORS.length] }}
                    />
                    {entry.name}
                  </span>
                  <span>{money(entry.value, base)}</span>
                </li>
              ))}
            </ul>
          </Card>

          {hasReminders ? (
            <Card className="p-5">
              <CardHeader title="提醒" />
              <ul className="mt-2 space-y-2 text-sm">
                {data.matured_investments.map((item) => (
                  <li key={item.id} className="flex items-start gap-2">
                    <CalendarClock className="mt-0.5 h-4 w-4 text-amber-600" />
                    <span className="text-slate-700">
                      「{item.name}」已于 {item.end_date.slice(0, 10)} 到期，市值{" "}
                      {money(item.current_value, item.currency)}
                    </span>
                  </li>
                ))}
                {dueSoon.map(({ loan, days }) => (
                  <li key={loan.id} className="flex items-start gap-2">
                    <CalendarClock className="mt-0.5 h-4 w-4 text-red-600" />
                    <span className="text-slate-700">
                      「{loan.name}」还款日每月 {loan.due_day} 日
                      {days === 0 ? "（今天）" : `（还有 ${days} 天）`}
                    </span>
                  </li>
                ))}
                {data.unmapped_cash !== "0E-8" ? (
                  <li className="flex items-start gap-2">
                    <TrendingDown className="mt-0.5 h-4 w-4 text-slate-500" />
                    <span className="text-slate-700">
                      投资账户存在未映射现金（{money(data.unmapped_cash, base)}），建议核对入金记录
                    </span>
                  </li>
                ) : null}
              </ul>
            </Card>
          ) : null}
        </div>
      </div>

      <Card className="p-5">
        <button
          type="button"
          className="flex w-full items-center justify-between text-left"
          onClick={() => setGuideOpen((open) => !open)}
        >
          <span className="text-sm font-semibold text-slate-900">概念指南：净资产是怎么算的？</span>
          <ChevronDown
            className={`h-4 w-4 text-slate-400 transition-transform ${guideOpen ? "rotate-180" : ""}`}
          />
        </button>
        {guideOpen ? (
          <div className="mt-3 space-y-2 text-sm leading-relaxed text-slate-600">
            <p>
              <strong className="text-slate-800">
                净资产 = 现金 + 投资账户余额 + 浮盈 − 负债。
              </strong>{" "}
              闲置现金是非投资账户的正余额（信用卡欠款算负债，溢缴款算现金）。每笔投资都挂在投资账户上：
              本金来自转账入金，或来自期初建仓（现金来源不追溯，记入该账户的期初余额）。市值相对本金的差额记为浮盈。
            </p>
            <p>
              <strong className="text-slate-800">入金为什么是转账？</strong>{" "}
              如果把买入记成支出，家庭总资产会被错误地削减。转账只是把钱换到投资账户；
              期初建仓则把已有持仓记进该账户的期初余额。真正的盈亏只在赎回时结算为「投资收益 / 投资亏损」。
            </p>
            <p>
              <strong className="text-slate-800">到期 ≠ 赎回。</strong>{" "}
              到期只是提醒，市值仍计入净资产；只有你显式赎回，资金才会回到现金账户并结算损益。
            </p>
          </div>
        ) : null}
      </Card>
    </div>
  );
}

function errorMessageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "加载失败，请稍后重试";
}

function compactNumber(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 100_000_000) return `${(value / 100_000_000).toFixed(1)}亿`;
  if (abs >= 10_000) return `${(value / 10_000).toFixed(1)}万`;
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function daysUntilDueDay(dueDay: number): number | null {
  const now = new Date();
  const today = now.getDate();
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const target = Math.min(dueDay, daysInMonth);
  return target >= today ? target - today : target + daysInMonth - today;
}
