import { Link } from "@tanstack/react-router";
import { ChevronDown, CreditCard, Landmark, TrendingUp, Wallet } from "lucide-react";
import { useState } from "react";

import type { CurrencyBalance, CurrencyBalanceTotal } from "../../api/types";
import { cn, errorMessage, money } from "../../lib/utils";
import { Badge, Card, CardHeader, EmptyState, ErrorBanner, Spinner } from "../ui";

export interface AccountBalanceEntry {
  account_id: string;
  name: string;
  account_type: string;
  is_active: boolean;
  balances: CurrencyBalance[];
}

export interface AccountBalancesData {
  base_currency: string;
  balances: CurrencyBalanceTotal[];
  accounts: AccountBalanceEntry[];
}

const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  bank: "银行卡",
  cash: "现金",
  wallet: "电子钱包",
  credit: "信用卡",
  investment: "投资账户",
  other: "其他",
};

const ACCOUNT_TYPE_TONES: Record<string, "slate" | "blue" | "amber" | "green" | "red"> = {
  bank: "slate",
  cash: "green",
  wallet: "green",
  credit: "amber",
  investment: "blue",
  other: "slate",
};

const DEFAULT_VISIBLE_ACCOUNTS = 6;

type ViewMode = "currency" | "account";

export function AccountDistributionCard({
  data,
  isLoading,
  isError,
  error,
}: {
  data?: AccountBalancesData;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
}) {
  const [mode, setMode] = useState<ViewMode>("currency");
  const [expandedCurrencies, setExpandedCurrencies] = useState<Record<string, boolean>>({});
  const [showAllAccounts, setShowAllAccounts] = useState(false);

  const toggleCurrency = (currency: string) => {
    setExpandedCurrencies((prev) => ({ ...prev, [currency]: !prev[currency] }));
  };

  const accounts = data?.accounts ?? [];
  const currencyTotals = data?.balances ?? [];

  const sortedAccounts = [...accounts].sort((a, b) => {
    if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
    const aHas = a.balances.length > 0 ? 1 : 0;
    const bHas = b.balances.length > 0 ? 1 : 0;
    if (aHas !== bHas) return bHas - aHas;
    return a.name.localeCompare(b.name, "zh-CN");
  });

  const visibleAccounts = showAllAccounts
    ? sortedAccounts
    : sortedAccounts.slice(0, DEFAULT_VISIBLE_ACCOUNTS);

  return (
    <Card>
      <CardHeader
        title="资产分布"
        description="各账户账面余额（含投资本金，不含浮盈与贷款）"
        action={
          <div className="inline-flex rounded-xl border border-ink/10 bg-canvas/70 p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setMode("currency")}
              className={cn(
                "rounded-lg px-2.5 py-1 font-medium transition",
                mode === "currency"
                  ? "bg-white text-ink shadow-sm"
                  : "text-ink/55 hover:text-ink",
              )}
            >
              按币种
            </button>
            <button
              type="button"
              onClick={() => setMode("account")}
              className={cn(
                "rounded-lg px-2.5 py-1 font-medium transition",
                mode === "account"
                  ? "bg-white text-ink shadow-sm"
                  : "text-ink/55 hover:text-ink",
              )}
            >
              按账户
            </button>
          </div>
        }
      />

      {isLoading ? (
        <Spinner />
      ) : isError ? (
        <div className="p-5">
          <ErrorBanner message={errorMessage(error)} />
        </div>
      ) : mode === "currency" ? (
        currencyTotals.length ? (
          <ul className="divide-y divide-ink/6">
            {currencyTotals.map((item) => {
              const expanded = Boolean(expandedCurrencies[item.currency]);
              const matchedAccounts = accounts
                .map((account) => {
                  const line = account.balances.find((b) => b.currency === item.currency);
                  return line ? { account, balance: line.book_balance } : null;
                })
                .filter(
                  (entry): entry is { account: AccountBalanceEntry; balance: string } =>
                    entry !== null,
                )
                .sort((a, b) => Math.abs(Number(b.balance)) - Math.abs(Number(a.balance)));

              const totalNum = Number(item.book_balance);
              return (
                <li key={item.currency}>
                  <button
                    type="button"
                    onClick={() => toggleCurrency(item.currency)}
                    className="flex w-full items-center justify-between gap-2 px-5 py-3.5 text-left transition hover:bg-canvas/50"
                  >
                    <span className="flex items-center gap-2 text-sm text-ink/75">
                      <ChevronDown
                        className={cn(
                          "h-4 w-4 text-ink/35 transition-transform",
                          expanded && "rotate-180",
                        )}
                      />
                      <span className="font-medium text-ink">{item.currency}</span>
                      <span className="text-xs text-ink/40">{matchedAccounts.length} 个账户</span>
                    </span>
                    <span
                      className={cn(
                        "text-sm font-semibold tabular-nums",
                        totalNum < 0 ? "text-red-600" : "text-ink",
                      )}
                    >
                      {money(item.book_balance, item.currency)}
                    </span>
                  </button>

                  {expanded ? (
                    <ul className="border-t border-ink/6 bg-canvas/40 px-5 py-2">
                      {matchedAccounts.map(({ account, balance }) => {
                        const num = Number(balance);
                        return (
                          <li
                            key={account.account_id}
                            className="flex items-center justify-between gap-2 py-1.5 text-xs"
                          >
                            <span className="flex min-w-0 items-center gap-1.5">
                              <AccountIcon type={account.account_type} />
                              <span className="truncate font-medium text-ink/80">
                                {account.name}
                              </span>
                              <Badge
                                tone={ACCOUNT_TYPE_TONES[account.account_type] ?? "slate"}
                                className="shrink-0 px-1.5 py-0 text-[10px]"
                              >
                                {ACCOUNT_TYPE_LABELS[account.account_type] ?? account.account_type}
                              </Badge>
                              {!account.is_active ? (
                                <span className="shrink-0 text-[10px] text-ink/40">停用</span>
                              ) : null}
                            </span>
                            <span
                              className={cn(
                                "shrink-0 font-medium tabular-nums",
                                num < 0 ? "text-red-600" : "text-ink/80",
                              )}
                            >
                              {money(balance, item.currency)}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState title="暂无账户余额" description="创建账户并设置期初余额后显示。" />
        )
      ) : sortedAccounts.length ? (
        <>
          <ul className="divide-y divide-ink/6">
            {visibleAccounts.map((account) => (
              <li
                key={account.account_id}
                className="flex items-start justify-between gap-3 px-5 py-3"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <AccountIcon type={account.account_type} />
                    <span className="truncate text-sm font-medium text-ink">{account.name}</span>
                    <Badge
                      tone={ACCOUNT_TYPE_TONES[account.account_type] ?? "slate"}
                      className="px-1.5 py-0 text-[10px]"
                    >
                      {ACCOUNT_TYPE_LABELS[account.account_type] ?? account.account_type}
                    </Badge>
                    {!account.is_active ? (
                      <Badge tone="slate" className="px-1.5 py-0 text-[10px]">
                        停用
                      </Badge>
                    ) : null}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  {account.balances.length ? (
                    <ul className="space-y-0.5">
                      {account.balances.map((line) => {
                        const num = Number(line.book_balance);
                        return (
                          <li
                            key={line.currency}
                            className={cn(
                              "text-xs font-medium tabular-nums",
                              num < 0 ? "text-red-600" : "text-ink",
                            )}
                          >
                            {money(line.book_balance, line.currency)}
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <span className="text-xs text-ink/35">0.00</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {sortedAccounts.length > DEFAULT_VISIBLE_ACCOUNTS ? (
            <div className="border-t border-ink/6 px-5 py-2 text-center">
              <button
                type="button"
                onClick={() => setShowAllAccounts((prev) => !prev)}
                className="inline-flex items-center gap-1 text-xs font-medium text-ink/55 transition hover:text-primary-700"
              >
                {showAllAccounts
                  ? "收起部分账户"
                  : `展开全部 ${sortedAccounts.length} 个账户`}
                <ChevronDown
                  className={cn("h-3.5 w-3.5 transition-transform", showAllAccounts && "rotate-180")}
                />
              </button>
            </div>
          ) : null}
        </>
      ) : (
        <EmptyState title="暂无账户" description="前往账户页创建第一个账户。" />
      )}

      {accounts.length > 0 ? (
        <div className="border-t border-ink/6 px-5 py-2.5 text-right">
          <Link
            to="/accounts"
            className="text-xs font-medium text-primary-700 transition hover:text-primary-800"
          >
            管理全部账户 →
          </Link>
        </div>
      ) : null}
    </Card>
  );
}

function AccountIcon({ type }: { type: string }) {
  const cls = "h-3.5 w-3.5 shrink-0 text-ink/40";
  if (type === "credit") return <CreditCard className={cls} />;
  if (type === "investment") return <TrendingUp className="h-3.5 w-3.5 shrink-0 text-blue-600" />;
  if (type === "cash" || type === "wallet") return <Wallet className={cls} />;
  return <Landmark className={cls} />;
}
