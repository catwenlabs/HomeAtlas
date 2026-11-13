import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeDollarSign,
  ChevronDown,
  CircleDollarSign,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { investmentsApi, investmentTagsApi, marketApi } from "../../api/endpoints";
import type { Investment } from "../../api/types";
import { cn, formatDate, money } from "../../lib/utils";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "../ui";
import { FundModal, InvestmentFormModal, RedeemModal } from "./InvestmentModals";

const TYPE_LABELS: Record<string, string> = {
  fixed: "定期",
  daily: "活期",
  fund: "基金",
  cash: "现金",
  stock: "股票",
  bond: "债券",
  other: "其他",
};

type StatusFilter = "" | "active" | "matured" | "redeemed";

export function InvestmentsTab() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StatusFilter>("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Investment | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["investments", "tab", status],
    queryFn: () =>
      investmentsApi.list(status ? { status, page_size: 200 } : { page_size: 200 }),
  });
  const tags = useQuery({
    queryKey: ["investment-tags"],
    queryFn: investmentTagsApi.list,
    staleTime: 60 * 1000,
  });
  const items = list.data?.items ?? [];

  const remove = useMutation({
    mutationFn: investmentsApi.remove,
    onSuccess: invalidateInvestments,
  });

  function invalidateInvestments() {
    queryClient.invalidateQueries({ queryKey: ["investments"] });
    queryClient.invalidateQueries({ queryKey: ["assets"] });
  }

  const tagNames = new Map((tags.data?.items ?? []).map((tag) => [tag.id, tag.name]));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {(
          [
            ["", "全部"],
            ["active", "在投"],
            ["matured", "已到期"],
            ["redeemed", "已赎回"],
          ] as [StatusFilter, string][]
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setStatus(value)}
            className={cn(
              "rounded-full border px-3.5 py-1.5 text-sm transition",
              status === value
                ? "border-primary-500 bg-primary-50 text-primary-700"
                : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
            )}
          >
            {label}
          </button>
        ))}
        <span className="flex-1" />
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-primary-700"
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          <Plus className="h-4 w-4" />
          登记投资
        </button>
      </div>

      {remove.isError ? <ErrorBanner message={errorMessage(remove.error)} /> : null}

      {list.isLoading ? (
        <Spinner />
      ) : list.isError ? (
        <ErrorBanner message={errorMessage(list.error)} />
      ) : items.length === 0 ? (
        <EmptyState
          title="还没有投资"
          description="登记第一笔：股票推荐「独立快照」方式（不关联账户），理财可选择托管并同事务入金。"
        />
      ) : (
        <div className="space-y-3">
          {items.map((investment) => (
            <InvestmentRow
              key={investment.id}
              investment={investment}
              tagNames={tagNames}
              expanded={expandedId === investment.id}
              onToggle={() =>
                setExpandedId((current) => (current === investment.id ? null : investment.id))
              }
              onEdit={() => {
                setEditing(investment);
                setFormOpen(true);
              }}
              onDelete={() => {
                if (
                  window.confirm(
                    `删除投资「${investment.name}」？需先冲正全部关联转账，否则会被拒绝。`,
                  )
                ) {
                  remove.mutate(investment.id);
                }
              }}
              onMutated={invalidateInvestments}
            />
          ))}
        </div>
      )}

      <InvestmentFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        investment={editing}
        defaultManaged={false}
      />
    </div>
  );
}

// useQueryClient is called via the hook at the top of InvestmentsTab and
// threaded down through onMutated.

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "操作失败，请稍后重试";
}

interface InvestmentRowProps {
  investment: Investment;
  tagNames: Map<string, string>;
  expanded: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onMutated: () => void;
}

function InvestmentRow({
  investment,
  tagNames,
  expanded,
  onToggle,
  onEdit,
  onDelete,
  onMutated,
}: InvestmentRowProps) {
  const [fundOpen, setFundOpen] = useState(false);
  const [redeemOpen, setRedeemOpen] = useState(false);
  const [valueDraft, setValueDraft] = useState<string>("");
  const [actionError, setActionError] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["investments", "detail", investment.id],
    queryFn: () => investmentsApi.get(investment.id),
    enabled: expanded,
  });
  const holdings = useQuery({
    queryKey: ["investments", "holdings", investment.id],
    queryFn: () => investmentsApi.holdings(investment.id),
    enabled: expanded && (investment.investment_type === "stock" || investment.investment_type === "fund"),
  });

  const symbols = (holdings.data?.items ?? []).map((item) => `${item.market}:${item.symbol}`);
  const quotes = useQuery({
    queryKey: ["market", "quotes", symbols.join(",")],
    queryFn: () => marketApi.quotes(symbols),
    enabled: symbols.length > 0 && expanded,
    staleTime: 30 * 1000,
  });
  const quoteBySymbol = new Map(
    (quotes.data?.items ?? []).map((quote) => [`${quote.market}:${quote.symbol}`, quote]),
  );

  const setValue = useMutation({
    mutationFn: (current_value: string) => investmentsApi.setValue(investment.id, current_value),
    onSuccess: onMutated,
    onError: (error) => setActionError(errorMessage(error)),
  });
  const refresh = useMutation({
    mutationFn: () => investmentsApi.refreshValue(investment.id),
    onSuccess: onMutated,
    onError: (error) => setActionError(errorMessage(error)),
  });

  const managed = investment.account_id !== null;
  const pnl =
    investment.status === "active"
      ? Number(investment.current_value) - Number(investment.principal)
      : Number(investment.realized_pnl ?? 0);

  return (
    <Card className="p-0">
      <button
        type="button"
        className="flex w-full flex-wrap items-center gap-3 p-4 text-left"
        onClick={onToggle}
      >
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-slate-400 transition-transform",
            expanded && "rotate-180",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium text-slate-900">{investment.name}</p>
            <Badge>{TYPE_LABELS[investment.investment_type] ?? investment.investment_type}</Badge>
            {managed ? null : <Badge tone="slate">独立快照</Badge>}
            {investment.matured ? <Badge tone="amber">已到期</Badge> : null}
            {investment.status === "redeemed" ? <Badge tone="slate">已赎回</Badge> : null}
            {investment.tag_ids.map((id) =>
              tagNames.get(id) ? <Badge key={id} tone="blue">{tagNames.get(id)}</Badge> : null,
            )}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {managed ? `托管 · 本金 ${investment.principal}` : `登记本金 ${investment.principal}`}{" "}
            {investment.currency}
            {investment.end_date ? ` · 到期 ${formatDate(investment.end_date)}` : ""}
          </p>
        </div>
        <div className="text-right">
          <p className="font-semibold text-slate-900">
            {money(investment.current_value, investment.currency)}
          </p>
          <p
            className={cn(
              "text-xs",
              pnl > 0 ? "text-emerald-600" : pnl < 0 ? "text-red-600" : "text-slate-500",
            )}
          >
            {investment.status === "active" ? "浮动" : "已实现"} {pnl.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </p>
        </div>
      </button>

      {expanded ? (
        <div className="border-t border-slate-100 p-4">
          {actionError ? <ErrorBanner message={actionError} /> : null}

          {investment.status === "active" ? (
            <div className="flex flex-wrap items-end gap-2">
              <label className="text-xs font-medium text-slate-600">
                当前估值
                <input
                  className="mt-1 block w-36 rounded-xl border border-slate-200 px-3 py-2 text-sm"
                  inputMode="decimal"
                  defaultValue={investment.current_value}
                  onChange={(event) => setValueDraft(event.target.value)}
                />
              </label>
              <button
                type="button"
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:border-slate-300"
                disabled={setValue.isPending || !valueDraft}
                onClick={() => valueDraft && setValue.mutate(valueDraft)}
              >
                <Pencil className="mr-1 inline h-3.5 w-3.5" />
                保存估值
              </button>
              {investment.investment_type === "stock" || investment.investment_type === "fund" ? (
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-xl border border-primary-200 bg-primary-50 px-3 py-2 text-sm font-medium text-primary-700 transition hover:bg-primary-100 disabled:opacity-50"
                  disabled={refresh.isPending}
                  onClick={() => {
                    setActionError(null);
                    refresh.mutate();
                  }}
                >
                  <RefreshCw className={cn("h-3.5 w-3.5", refresh.isPending && "animate-spin")} />
                  {refresh.isPending ? "刷新中…" : "按行情刷新市值"}
                </button>
              ) : null}
              {managed ? (
                <>
                  <button
                    type="button"
                    className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:border-slate-300"
                    onClick={() => setFundOpen(true)}
                  >
                    <CircleDollarSign className="mr-1 inline h-3.5 w-3.5" />
                    追加入金
                  </button>
                  <button
                    type="button"
                    className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100"
                    onClick={() => setRedeemOpen(true)}
                  >
                    <BadgeDollarSign className="mr-1 inline h-3.5 w-3.5" />
                    全额赎回
                  </button>
                </>
              ) : null}
              <button
                type="button"
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:border-slate-300"
                onClick={onEdit}
              >
                编辑
              </button>
              <button
                type="button"
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-red-600 transition hover:border-red-200"
                onClick={onDelete}
              >
                <Trash2 className="mr-1 inline h-3.5 w-3.5" />
                删除
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
              <span>
                已实现损益{" "}
                <strong className={pnl >= 0 ? "text-emerald-600" : "text-red-600"}>
                  {pnl.toLocaleString("zh-CN", { minimumFractionDigits: 2 })} {investment.currency}
                </strong>
              </span>
              {investment.pre_redeem_value ? (
                <span>· 赎回前估值 {investment.pre_redeem_value}</span>
              ) : null}
            </div>
          )}

          {refresh.isSuccess && refresh.data ? (
            <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm">
              <p className="font-medium text-emerald-800">
                市值已更新：{refresh.data.previous_value} → {refresh.data.current_value}{" "}
                {investment.currency}
              </p>
              <ul className="mt-1 space-y-0.5 text-xs text-emerald-700">
                {refresh.data.items.map((item) => (
                  <li key={`${item.market}:${item.symbol}`}>
                    {item.symbol}（{item.name}）× {item.quantity} @ {item.price} = {item.subtotal}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {holdings.isLoading ? (
            <Spinner label="加载持股…" />
          ) : (holdings.data?.items.length ?? 0) > 0 ? (
            <div className="mt-4">
              <p className="text-sm font-semibold text-slate-900">
                持股明细 · 持仓成本 {holdings.data?.holdings_cost} {investment.currency}
              </p>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                      <th className="py-2 pr-4">市场</th>
                      <th className="py-2 pr-4">代码</th>
                      <th className="py-2 pr-4">数量</th>
                      <th className="py-2 pr-4">成本价</th>
                      <th className="py-2 pr-4">现价</th>
                      <th className="py-2 pr-4">市值</th>
                      <th className="py-2 pr-4">浮动盈亏</th>
                      <th className="py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {(holdings.data?.items ?? []).map((holding) => {
                      const quote = quoteBySymbol.get(`${holding.market}:${holding.symbol}`);
                      const marketValue = quote
                        ? Number(holding.quantity) * Number(quote.price)
                        : null;
                      const cost = Number(holding.quantity) * Number(holding.cost_price);
                      return (
                        <tr key={holding.id} className="border-b border-slate-50">
                          <td className="py-2 pr-4 text-slate-500">{holding.market}</td>
                          <td className="py-2 pr-4 font-mono text-slate-800">{holding.symbol}</td>
                          <td className="py-2 pr-4">{Number(holding.quantity).toLocaleString()}</td>
                          <td className="py-2 pr-4">{Number(holding.cost_price).toLocaleString()}</td>
                          <td className="py-2 pr-4">
                            {quote ? (
                              <span title={`更新于 ${new Date(quote.quoted_at).toLocaleTimeString("zh-CN")}`}>
                                {Number(quote.price).toLocaleString()}
                              </span>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>
                          <td className="py-2 pr-4">
                            {marketValue === null ? (
                              <span className="text-slate-400">—</span>
                            ) : (
                              marketValue.toLocaleString("zh-CN", { maximumFractionDigits: 2 })
                            )}
                          </td>
                          <td
                            className={cn(
                              "py-2 pr-4",
                              marketValue === null
                                ? "text-slate-400"
                                : marketValue - cost >= 0
                                  ? "text-emerald-600"
                                  : "text-red-600",
                            )}
                          >
                            {marketValue === null
                              ? "—"
                              : (marketValue - cost).toLocaleString("zh-CN", {
                                  minimumFractionDigits: 2,
                                  maximumFractionDigits: 2,
                                })}
                          </td>
                          <td className="py-2 text-right">
                            <button
                              type="button"
                              className="text-xs text-slate-400 transition hover:text-red-600"
                              onClick={() => {
                                if (window.confirm(`移除持股 ${holding.symbol}？`)) {
                                  investmentsApi
                                    .removeHolding(investment.id, holding.id)
                                    .then(onMutated)
                                    .catch((error) => setActionError(errorMessage(error)));
                                }
                              }}
                            >
                              移除
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <HoldingForm investmentId={investment.id} onSaved={onMutated} />
            </div>
          ) : null}

          {detail.data?.holdings_cost && (holdings.data?.items.length ?? 0) === 0 ? (
            <p className="mt-3 text-xs text-slate-400">此投资还没有持股记录。</p>
          ) : null}
        </div>
      ) : null}

      <FundModal investment={fundOpen ? investment : null} onClose={() => setFundOpen(false)} />
      <RedeemModal investment={redeemOpen ? investment : null} onClose={() => setRedeemOpen(false)} />
    </Card>
  );
}

function HoldingForm({ investmentId, onSaved }: { investmentId: string; onSaved: () => void }) {
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="mt-3 flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        const form = event.currentTarget;
        const data = new FormData(form);
        investmentsApi
          .addHolding(investmentId, {
            market: String(data.get("market") ?? "SH") as "SH",
            symbol: String(data.get("symbol") ?? "").toUpperCase(),
            quantity: String(data.get("quantity") ?? ""),
            cost_price: String(data.get("cost_price") ?? ""),
          })
          .then(() => {
            form.reset();
            onSaved();
          })
          .catch((err) => setError(err instanceof ApiError ? err.message : "添加失败"));
      }}
    >
      <label className="text-xs font-medium text-slate-600">
        市场
        <select
          name="market"
          className="mt-1 block rounded-xl border border-slate-200 px-2.5 py-2 text-sm"
          defaultValue="SH"
        >
          <option value="SH">沪 SH</option>
          <option value="SZ">深 SZ</option>
          <option value="HK">港 HK</option>
          <option value="US">美 US</option>
        </select>
      </label>
      <label className="text-xs font-medium text-slate-600">
        代码
        <input
          name="symbol"
          required
          maxLength={20}
          placeholder="600519"
          className="mt-1 block w-28 rounded-xl border border-slate-200 px-3 py-2 text-sm"
        />
      </label>
      <label className="text-xs font-medium text-slate-600">
        数量
        <input
          name="quantity"
          required
          inputMode="decimal"
          placeholder="100"
          className="mt-1 block w-24 rounded-xl border border-slate-200 px-3 py-2 text-sm"
        />
      </label>
      <label className="text-xs font-medium text-slate-600">
        成本单价
        <input
          name="cost_price"
          required
          inputMode="decimal"
          placeholder="1700"
          className="mt-1 block w-28 rounded-xl border border-slate-200 px-3 py-2 text-sm"
        />
      </label>
      <button
        type="submit"
        className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm text-slate-700 transition hover:border-slate-300"
      >
        添加持股
      </button>
      {error ? <span className="text-xs text-red-600">{error}</span> : null}
    </form>
  );
}
