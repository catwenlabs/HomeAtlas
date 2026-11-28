import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronDown, RefreshCw } from "lucide-react";
import { useState } from "react";

import { investmentsApi, marketApi } from "../../api/endpoints";
import type { HouseholdHolding, Quote } from "../../api/types";
import {
  amount,
  cn,
  errorMessage,
  formatQuantity,
  money,
  pnlClass,
  pnlPercent,
  signedAmount,
  signedPercent,
} from "../../lib/utils";
import { Badge, Card, CardHeader, ErrorBanner, Spinner } from "../ui";

const DEFAULT_VISIBLE_ROWS = 8;

async function fetchAllQuotes(symbols: string[]): Promise<Quote[]> {
  const items: Quote[] = [];
  for (let i = 0; i < symbols.length; i += 50) {
    const res = await marketApi.quotes(symbols.slice(i, i + 50));
    items.push(...res.items);
  }
  return items;
}

interface HoldingRowView {
  holding: HouseholdHolding;
  quote?: Quote;
  cost: number;
  marketValue: number | null;
  pnl: number | null;
  pnlRate: number | null;
}

export function HoldingsCard({
  base,
  fxRates,
}: {
  base: string;
  fxRates?: Record<string, string>;
}) {
  const queryClient = useQueryClient();
  const [showAll, setShowAll] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const holdings = useQuery({
    queryKey: ["investments", "holdings", "all"],
    queryFn: investmentsApi.allHoldings,
  });

  const items = holdings.data?.items ?? [];
  const uniqueSymbols = Array.from(
    new Set(items.map((item) => `${item.market}:${item.symbol}`)),
  ).sort();

  const quotes = useQuery({
    queryKey: ["market", "quotes", uniqueSymbols.join(",")],
    queryFn: () => fetchAllQuotes(uniqueSymbols),
    enabled: uniqueSymbols.length > 0,
    staleTime: 30 * 1000,
    retry: false,
  });

  const quoteBySymbol = new Map(
    (quotes.data ?? []).map((quote) => [`${quote.market}:${quote.symbol}`, quote]),
  );

  const syncValues = useMutation({
    mutationFn: async () => {
      const investmentIds = Array.from(new Set(items.map((item) => item.investment_id)));
      const results = await Promise.allSettled(
        investmentIds.map((id) => investmentsApi.refreshValue(id)),
      );
      const succeeded = results.filter((r) => r.status === "fulfilled").length;
      const firstRejected = results.find(
        (r): r is PromiseRejectedResult => r.status === "rejected",
      );
      if (succeeded === 0 && firstRejected) {
        throw firstRejected.reason;
      }
      return { succeeded, total: investmentIds.length, failed: investmentIds.length - succeeded };
    },
    onSuccess: (result) => {
      setSyncError(null);
      setSyncNotice(
        result.failed > 0
          ? `已同步 ${result.succeeded}/${result.total} 笔投资市值（部分标的暂无行情）`
          : `已按最新行情同步 ${result.succeeded} 笔投资市值`,
      );
      queryClient.invalidateQueries({ queryKey: ["investments"] });
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      queryClient.invalidateQueries({ queryKey: ["market", "quotes"] });
    },
    onError: (err) => {
      setSyncNotice(null);
      setSyncError(errorMessage(err));
    },
  });

  if (holdings.isLoading) {
    return (
      <Card className="mt-6">
        <CardHeader title="股票持仓" description="加载家庭在投股票与基金持仓…" />
        <Spinner />
      </Card>
    );
  }

  if (holdings.isError) {
    return (
      <Card className="mt-6">
        <CardHeader title="股票持仓" />
        <div className="p-5">
          <ErrorBanner message={errorMessage(holdings.error)} />
        </div>
      </Card>
    );
  }

  if (items.length === 0) {
    const stockCount = holdings.data?.stock_investment_count ?? 0;
    return (
      <Card className="mt-6 flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">股票持仓</h2>
          <p className="mt-0.5 text-xs text-ink/50">
            {stockCount > 0
              ? `已有 ${stockCount} 笔股票/基金投资，尚未录入成交记录。`
              : "暂无股票或基金持仓，登记投资并录入成交后可在此直接查看市值与浮盈。"}
          </p>
        </div>
        <Link
          to="/assets"
          search={{ tab: "investments" }}
          className="text-xs font-medium text-primary-700 transition hover:text-primary-800"
        >
          {stockCount > 0 ? "前往录入成交 →" : "前往登记投资 →"}
        </Link>
      </Card>
    );
  }

  const fxToBase = (currency: string): number | null => {
    if (currency === base) return 1;
    const raw = fxRates?.[currency];
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  };

  const rows: HoldingRowView[] = items.map((holding) => {
    const quote = quoteBySymbol.get(`${holding.market}:${holding.symbol}`);
    const cost =
      holding.cost_subtotal !== null
        ? Number(holding.cost_subtotal)
        : Number(holding.quantity) * Number(holding.cost_price);
    const marketValue = quote ? Number(holding.quantity) * Number(quote.price) : null;
    const pnl = marketValue === null ? null : marketValue - cost;
    const pnlRate = marketValue === null ? null : pnlPercent(marketValue, cost);
    return { holding, quote, cost, marketValue, pnl, pnlRate };
  });

  const currencies = Array.from(new Set(rows.map((r) => r.holding.currency))).sort();
  const isSingleCurrency = currencies.length === 1;
  const canConvertAll = !isSingleCurrency && currencies.every((c) => fxToBase(c) !== null);
  const summaryCurrency = isSingleCurrency ? currencies[0] : canConvertAll ? base : null;

  rows.sort((a, b) => {
    const aRate = summaryCurrency ? (fxToBase(a.holding.currency) ?? 1) : 1;
    const bRate = summaryCurrency ? (fxToBase(b.holding.currency) ?? 1) : 1;
    const aVal = (a.marketValue ?? a.cost) * aRate;
    const bVal = (b.marketValue ?? b.cost) * bRate;
    return bVal - aVal;
  });

  const allQuoted = rows.every((r) => r.marketValue !== null);
  const latestQuotedAt = (quotes.data ?? []).reduce<string | null>((latest, quote) => {
    if (!latest || quote.quoted_at > latest) return quote.quoted_at;
    return latest;
  }, null);

  let totalCost: number | null = null;
  let totalMarketValue: number | null = null;
  let totalPnl: number | null = null;
  let totalPnlRate: number | null = null;

  if (summaryCurrency) {
    totalCost = rows.reduce((sum, r) => {
      const rate = isSingleCurrency ? 1 : (fxToBase(r.holding.currency) ?? 1);
      return sum + r.cost * rate;
    }, 0);
    if (allQuoted) {
      totalMarketValue = rows.reduce((sum, r) => {
        const rate = isSingleCurrency ? 1 : (fxToBase(r.holding.currency) ?? 1);
        return sum + (r.marketValue ?? 0) * rate;
      }, 0);
      totalPnl = totalMarketValue - totalCost;
      totalPnlRate = pnlPercent(totalMarketValue, totalCost);
    }
  }

  const perCurrencySummary = currencies.map((currency) => {
    const subset = rows.filter((r) => r.holding.currency === currency);
    const cost = subset.reduce((sum, r) => sum + r.cost, 0);
    const quotedAll = subset.every((r) => r.marketValue !== null);
    const marketValue = quotedAll ? subset.reduce((sum, r) => sum + (r.marketValue ?? 0), 0) : null;
    const pnl = marketValue === null ? null : marketValue - cost;
    return { currency, cost, marketValue, pnl };
  });

  const visibleRows = showAll ? rows : rows.slice(0, DEFAULT_VISIBLE_ROWS);
  const hiddenCount = rows.length - visibleRows.length;
  const markets = Array.from(new Set(rows.map((r) => r.holding.market)));

  const subtitleParts = [`共 ${rows.length} 只标的`, `${markets.join(" / ")} 市场`];
  if (latestQuotedAt) {
    subtitleParts.push(`行情 ${new Date(latestQuotedAt).toLocaleTimeString("zh-CN")}`);
  } else if (quotes.isLoading) {
    subtitleParts.push("获取实时行情中…");
  } else if (quotes.isError) {
    subtitleParts.push("行情暂不可用，显示持仓成本");
  }

  return (
    <Card className="mt-6">
      <CardHeader
        title="股票持仓"
        description={subtitleParts.join(" · ")}
        action={
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={syncValues.isPending}
              onClick={() => {
                setSyncNotice(null);
                setSyncError(null);
                syncValues.mutate();
              }}
              className="inline-flex items-center gap-1.5 rounded-xl border border-ink/12 bg-white px-3 py-1.5 text-xs font-medium text-ink/75 transition hover:border-primary-300 hover:text-primary-700 disabled:opacity-50"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", syncValues.isPending && "animate-spin")} />
              {syncValues.isPending ? "同步中…" : "同步市值"}
            </button>
            <Link
              to="/assets"
              search={{ tab: "investments" }}
              className="rounded-xl bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-700 transition hover:bg-primary-100"
            >
              管理持仓 →
            </Link>
          </div>
        }
      />

      {syncError ? (
        <div className="px-5 pt-3">
          <ErrorBanner message={syncError} />
        </div>
      ) : null}
      {syncNotice ? (
        <p className="px-5 pt-3 text-xs text-primary-700">{syncNotice}</p>
      ) : null}

      <div className="border-b border-ink/8 bg-canvas/40 px-5 py-3.5">
        {summaryCurrency && totalCost !== null ? (
          <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
            <div>
              <p className="text-[11px] font-medium text-ink/45">
                持仓总市值{canConvertAll ? `（折合 ${summaryCurrency}）` : ""}
              </p>
              <p className="mt-0.5 text-lg font-semibold tabular-nums tracking-tight text-ink">
                {totalMarketValue !== null
                  ? money(totalMarketValue, summaryCurrency)
                  : quotes.isLoading
                    ? "获取行情中…"
                    : "—"}
              </p>
            </div>
            <div>
              <p className="text-[11px] font-medium text-ink/45">持仓总成本</p>
              <p className="mt-0.5 text-base font-medium tabular-nums text-ink/80">
                {money(totalCost, summaryCurrency)}
              </p>
            </div>
            <div>
              <p className="text-[11px] font-medium text-ink/45">持仓浮动盈亏</p>
              <p
                className={cn(
                  "mt-0.5 text-base font-semibold tabular-nums",
                  totalPnl === null ? "text-ink/40" : pnlClass(totalPnl),
                )}
              >
                {totalPnl === null
                  ? "—"
                  : `${signedAmount(totalPnl)} ${summaryCurrency}${
                      totalPnlRate === null ? "" : ` (${signedPercent(totalPnlRate)})`
                    }`}
              </p>
            </div>
            {!isSingleCurrency ? (
              <div className="ml-auto flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink/50">
                {perCurrencySummary.map((entry) => (
                  <span key={entry.currency} className="tabular-nums">
                    {entry.currency}{" "}
                    {entry.marketValue !== null
                      ? amount(entry.marketValue)
                      : `成本 ${amount(entry.cost)}`}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
            {perCurrencySummary.map((entry) => (
              <div key={entry.currency} className="flex items-baseline gap-2">
                <Badge>{entry.currency}</Badge>
                <span className="font-semibold tabular-nums text-ink">
                  {entry.marketValue !== null
                    ? money(entry.marketValue, entry.currency)
                    : `成本 ${money(entry.cost, entry.currency)}`}
                </span>
                {entry.pnl !== null ? (
                  <span className={cn("font-medium tabular-nums", pnlClass(entry.pnl))}>
                    {signedAmount(entry.pnl)}
                  </span>
                ) : null}
              </div>
            ))}
            <span className="text-ink/45">
              补录汇率后可折合 {base} 汇总
            </span>
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-ink/8 text-left text-xs text-ink/45">
              <th className="py-2.5 pl-5 pr-3 font-medium">标的</th>
              <th className="px-3 py-2.5 text-right font-medium">持仓</th>
              <th className="px-3 py-2.5 text-right font-medium">成本价</th>
              <th className="px-3 py-2.5 text-right font-medium">现价</th>
              <th className="px-3 py-2.5 text-right font-medium">市值</th>
              <th className="py-2.5 pl-3 pr-5 text-right font-medium">浮动盈亏</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink/6">
            {visibleRows.map(({ holding, quote, cost, marketValue, pnl, pnlRate }) => (
              <tr key={holding.id} className="transition hover:bg-canvas/50">
                <td className="py-3 pl-5 pr-3">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-ink">
                      {quote?.name || holding.symbol}
                    </span>
                    <span className="font-mono text-xs text-ink/50">{holding.symbol}</span>
                    <Badge className="px-1.5 py-0 text-[10px]">{holding.market}</Badge>
                    {holding.investment_type === "fund" ? (
                      <Badge tone="blue" className="px-1.5 py-0 text-[10px]">
                        基金
                      </Badge>
                    ) : null}
                  </div>
                  <Link
                    to="/assets"
                    search={{ tab: "investments", investment: holding.investment_id }}
                    className="mt-0.5 inline-block text-xs text-ink/45 transition hover:text-primary-700"
                  >
                    {holding.investment_name} · 成本 {money(cost, holding.currency)}
                  </Link>
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-ink/80">
                  {formatQuantity(holding.quantity)}
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-ink/65">
                  {amount(holding.cost_price)}
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-ink">
                  {quote ? (
                    <span title={`更新于 ${new Date(quote.quoted_at).toLocaleTimeString("zh-CN")}`}>
                      {amount(quote.price)}
                    </span>
                  ) : (
                    <span className="text-ink/30">—</span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-right font-medium tabular-nums text-ink">
                  {marketValue === null ? (
                    <span className="text-ink/30">—</span>
                  ) : (
                    <>
                      {amount(marketValue)}
                      <span className="ml-1 text-xs font-normal text-ink/45">
                        {holding.currency}
                      </span>
                    </>
                  )}
                </td>
                <td
                  className={cn(
                    "whitespace-nowrap py-3 pl-3 pr-5 text-right tabular-nums",
                    pnl === null ? "text-ink/30" : pnlClass(pnl),
                  )}
                >
                  {pnl === null ? (
                    "—"
                  ) : (
                    <div>
                      <p className="font-semibold">{signedAmount(pnl)}</p>
                      <p className="text-xs font-medium">
                        {pnlRate === null ? "" : signedPercent(pnlRate)}
                      </p>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.length > DEFAULT_VISIBLE_ROWS ? (
        <div className="border-t border-ink/8 px-5 py-2.5 text-center">
          <button
            type="button"
            onClick={() => setShowAll((prev) => !prev)}
            className="inline-flex items-center gap-1 text-xs font-medium text-ink/60 transition hover:text-primary-700"
          >
            {showAll ? "收起部分持仓" : `展开其余 ${hiddenCount} 只持仓`}
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", showAll && "rotate-180")} />
          </button>
        </div>
      ) : null}
    </Card>
  );
}
