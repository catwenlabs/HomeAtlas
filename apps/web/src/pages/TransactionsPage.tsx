import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { transactionsApi, type TransactionQuery } from "../api/endpoints";
import type { Transaction } from "../api/types";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Spinner,
  SuccessBanner,
} from "../components/ui";
import { useAccountNames, useAccounts, useCategories, useCurrencies } from "../hooks/useReference";
import { errorMessage, formatDate, money, todayInput } from "../lib/utils";
import { useAuth } from "../store/auth";

const PAGE_SIZE = 20;

interface FormState {
  account_id: string;
  category_id: string;
  transaction_type: "income" | "expense";
  amount: string;
  currency: string;
  transaction_date: string;
  description: string;
  status: "draft" | "confirmed";
}

function emptyForm(accountId = "", currency = "CNY"): FormState {
  return {
    account_id: accountId,
    category_id: "",
    transaction_type: "expense",
    amount: "",
    currency,
    transaction_date: todayInput(),
    description: "",
    status: "confirmed",
  };
}

export function TransactionsPage() {
  const queryClient = useQueryClient();
  const household = useAuth((state) => state.household);
  const accounts = useAccounts();
  const categories = useCategories();
  const currencies = useCurrencies();
  const accountNames = useAccountNames();

  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<TransactionQuery>({});
  const [keyword, setKeyword] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Transaction | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [message, setMessage] = useState<string | null>(null);

  const query: TransactionQuery = useMemo(
    () => ({
      page,
      page_size: PAGE_SIZE,
      sort_by: "transaction_date",
      sort_order: "desc",
      ...filters,
      keyword: keyword.trim() || undefined,
    }),
    [page, filters, keyword],
  );

  const list = useQuery({
    queryKey: ["transactions", query],
    queryFn: () => transactionsApi.list(query),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["transactions"] });
    await queryClient.invalidateQueries({ queryKey: ["statistics"] });
  };

  const create = useMutation({
    mutationFn: (payload: FormState) =>
      transactionsApi.create({
        account_id: payload.account_id,
        category_id: payload.category_id || null,
        transaction_type: payload.transaction_type,
        amount: payload.amount,
        currency: payload.currency,
        transaction_date: toIso(payload.transaction_date),
        description: payload.description || null,
        status: payload.status,
      }),
    onSuccess: async () => {
      setModalOpen(false);
      setMessage("记录已保存");
      await refresh();
    },
  });

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: FormState }) =>
      transactionsApi.update(id, {
        account_id: payload.account_id,
        category_id: payload.category_id || null,
        transaction_type: payload.transaction_type,
        amount: payload.amount,
        currency: payload.currency,
        transaction_date: toIso(payload.transaction_date),
        description: payload.description || null,
        status: payload.status,
      }),
    onSuccess: async () => {
      setModalOpen(false);
      setEditing(null);
      setMessage("记录已更新");
      await refresh();
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => transactionsApi.remove(id),
    onSuccess: async () => {
      setMessage("记录已删除");
      await refresh();
    },
  });

  const reverse = useMutation({
    mutationFn: (id: string) => transactionsApi.reverse(id),
    onSuccess: async () => {
      setMessage("已生成冲销记录");
      await refresh();
    },
  });

  function openCreate() {
    const first = accounts.data?.[0];
    setEditing(null);
    setForm(emptyForm(first?.id, first?.currency ?? household?.base_currency ?? "CNY"));
    setModalOpen(true);
  }

  function openEdit(transaction: Transaction) {
    setEditing(transaction);
    setForm({
      account_id: transaction.account_id,
      category_id: transaction.category_id ?? "",
      transaction_type: transaction.transaction_type === "income" ? "income" : "expense",
      amount: transaction.amount,
      currency: transaction.currency,
      transaction_date: transaction.transaction_date.slice(0, 10),
      description: transaction.description ?? "",
      status: transaction.status === "draft" ? "draft" : "confirmed",
    });
    setModalOpen(true);
  }

  const mutationError = create.error ?? update.error ?? remove.error ?? reverse.error;
  const totalPages = Math.max(1, Math.ceil((list.data?.total ?? 0) / PAGE_SIZE));
  const formCategories = (categories.data ?? []).filter(
    (category) => category.category_type === form.transaction_type && category.is_active,
  );

  return (
    <div>
      <PageHeader
        eyebrow="Transactions"
        title="收支记录"
        description="记录、修正与冲销每一笔家庭收支。"
        action={
          <Button onClick={openCreate} disabled={!accounts.data?.length}>
            <Plus className="h-4 w-4" />
            新增记录
          </Button>
        }
      />

      {!accounts.isLoading && !accounts.data?.length ? (
        <div className="mb-4">
          <ErrorBanner message="请先在“账户”页面创建至少一个账户。" />
        </div>
      ) : null}

      {message ? (
        <div className="mb-4">
          <SuccessBanner message={message} />
        </div>
      ) : null}
      {mutationError ? (
        <div className="mb-4">
          <ErrorBanner message={errorMessage(mutationError)} />
        </div>
      ) : null}

      <Card className="mb-4 p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field label="开始日期">
            <Input
              type="date"
              value={filters.start_date ?? ""}
              onChange={(event) =>
                setFilters((value) => ({ ...value, start_date: event.target.value || undefined }))
              }
            />
          </Field>
          <Field label="结束日期">
            <Input
              type="date"
              value={filters.end_date ?? ""}
              onChange={(event) =>
                setFilters((value) => ({ ...value, end_date: event.target.value || undefined }))
              }
            />
          </Field>
          <Field label="账户">
            <Select
              value={filters.account_id ?? ""}
              onChange={(event) =>
                setFilters((value) => ({ ...value, account_id: event.target.value || undefined }))
              }
            >
              <option value="">全部账户</option>
              {accounts.data?.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="类型">
            <Select
              value={filters.transaction_type ?? ""}
              onChange={(event) =>
                setFilters((value) => ({
                  ...value,
                  transaction_type:
                    (event.target.value as TransactionQuery["transaction_type"]) || undefined,
                }))
              }
            >
              <option value="">全部类型</option>
              <option value="income">收入</option>
              <option value="expense">支出</option>
              <option value="opening_balance">期初余额</option>
            </Select>
          </Field>
          <Field label="关键词">
            <Input
              value={keyword}
              placeholder="描述包含…"
              onChange={(event) => {
                setPage(1);
                setKeyword(event.target.value);
              }}
            />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink/45">
          <span>状态</span>
          {(["", "draft", "confirmed", "reversed"] as const).map((status) => (
            <button
              key={status || "all"}
              type="button"
              onClick={() => {
                setPage(1);
                setFilters((value) => ({ ...value, status: status || undefined }));
              }}
              className={`rounded-full border px-3 py-1 transition ${
                (filters.status ?? "") === status
                  ? "border-primary-300 bg-primary-50 text-primary-800"
                  : "border-ink/10 bg-white text-ink/50"
              }`}
            >
              {status === "" ? "全部" : status === "draft" ? "草稿" : status === "confirmed" ? "已确认" : "已冲销"}
            </button>
          ))}
          <Button
            variant="ghost"
            className="ml-auto h-8 px-2 text-xs"
            onClick={() => {
              setFilters({});
              setKeyword("");
              setPage(1);
            }}
          >
            重置筛选
          </Button>
        </div>
      </Card>

      <Card>
        {list.isLoading ? (
          <Spinner />
        ) : list.isError ? (
          <div className="p-5">
            <ErrorBanner message={errorMessage(list.error)} />
          </div>
        ) : list.data && list.data.items.length ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead>
                  <tr className="border-b border-ink/8 text-xs uppercase tracking-wide text-ink/40">
                    <th className="px-5 py-3 font-medium">日期</th>
                    <th className="px-3 py-3 font-medium">类型</th>
                    <th className="px-3 py-3 font-medium">账户 / 分类</th>
                    <th className="px-3 py-3 font-medium">描述</th>
                    <th className="px-3 py-3 text-right font-medium">金额</th>
                    <th className="px-3 py-3 font-medium">状态</th>
                    <th className="px-5 py-3 text-right font-medium">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink/6">
                  {list.data.items.map((transaction) => (
                    <tr key={transaction.id} className="hover:bg-canvas/40">
                      <td className="whitespace-nowrap px-5 py-3 text-xs text-ink/55">
                        {formatDate(transaction.transaction_date)}
                      </td>
                      <td className="px-3 py-3">
                        <Badge
                          tone={
                            transaction.transaction_type === "income"
                              ? "green"
                              : transaction.transaction_type === "expense"
                                ? "red"
                                : "blue"
                          }
                        >
                          {transaction.transaction_type === "income"
                            ? "收入"
                            : transaction.transaction_type === "expense"
                              ? "支出"
                              : "期初"}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 text-xs text-ink/60">
                        <p className="text-ink/80">
                          {accountNames.names.get(transaction.account_id) ?? "账户"}
                        </p>
                        <p>
                          {transaction.category_id
                            ? (categories.data ?? []).find(
                                (item) => item.id === transaction.category_id,
                              )?.name ?? "分类"
                            : "未分类"}
                        </p>
                      </td>
                      <td className="max-w-48 truncate px-3 py-3 text-xs text-ink/55">
                        {transaction.description || "—"}
                      </td>
                      <td
                        className={`whitespace-nowrap px-3 py-3 text-right font-medium ${
                          transaction.transaction_type === "income"
                            ? "text-primary-700"
                            : transaction.transaction_type === "expense"
                              ? "text-red-600"
                              : "text-blue-700"
                        }`}
                      >
                        {transaction.transaction_type === "income" ? "+" : transaction.transaction_type === "expense" ? "−" : ""}
                        {money(transaction.amount, transaction.currency)}
                      </td>
                      <td className="px-3 py-3">
                        <Badge
                          tone={
                            transaction.status === "confirmed"
                              ? "green"
                              : transaction.status === "draft"
                                ? "amber"
                                : "slate"
                          }
                        >
                          {transaction.status === "confirmed"
                            ? "已确认"
                            : transaction.status === "draft"
                              ? "草稿"
                              : "已冲销"}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-right">
                        <div className="flex justify-end gap-1">
                          {transaction.status === "draft" ? (
                            <Button
                              variant="ghost"
                              className="h-8 px-2"
                              title="编辑"
                              onClick={() => openEdit(transaction)}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                          ) : null}
                          {transaction.status === "confirmed" &&
                          transaction.transaction_type !== "opening_balance" &&
                          !transaction.transfer_id ? (
                            <Button
                              variant="ghost"
                              className="h-8 px-2"
                              title="冲销"
                              onClick={() => {
                                if (window.confirm("确认冲销这笔记录？将生成一条反向记录。")) {
                                  reverse.mutate(transaction.id);
                                }
                              }}
                            >
                              <RotateCcw className="h-3.5 w-3.5" />
                            </Button>
                          ) : null}
                          {transaction.status === "draft" ? (
                            <Button
                              variant="ghost"
                              className="h-8 px-2 text-red-600"
                              title="删除"
                              onClick={() => {
                                if (window.confirm("确认删除这笔记录？")) {
                                  remove.mutate(transaction.id);
                                }
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-ink/8 px-5 py-3 text-xs text-ink/45">
              <span>
                共 {list.data.total} 条 · 第 {list.data.page} / {totalPages} 页
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  className="h-8 px-3 text-xs"
                  disabled={page <= 1}
                  onClick={() => setPage((value) => value - 1)}
                >
                  上一页
                </Button>
                <Button
                  variant="outline"
                  className="h-8 px-3 text-xs"
                  disabled={page >= totalPages}
                  onClick={() => setPage((value) => value + 1)}
                >
                  下一页
                </Button>
              </div>
            </div>
          </>
        ) : (
          <EmptyState title="没有符合条件的记录" description="调整筛选条件，或新增一笔收支。" />
        )}
      </Card>

      <Modal
        open={modalOpen}
        title={editing ? "编辑收支记录" : "新增收支记录"}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
      >
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="账户">
              <Select
                value={form.account_id}
                onChange={(event) => {
                  const account = accounts.data?.find((item) => item.id === event.target.value);
                  setForm((value) => ({
                    ...value,
                    account_id: event.target.value,
                    currency: account?.currency ?? value.currency,
                  }));
                }}
              >
                {accounts.data?.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name} · {account.currency}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="类型">
              <Select
                value={form.transaction_type}
                onChange={(event) =>
                  setForm((value) => ({
                    ...value,
                    transaction_type: event.target.value as "income" | "expense",
                    category_id: "",
                  }))
                }
              >
                <option value="expense">支出</option>
                <option value="income">收入</option>
              </Select>
            </Field>
            <Field label="金额">
              <Input
                type="number"
                min="0"
                step="0.01"
                value={form.amount}
                onChange={(event) => setForm((value) => ({ ...value, amount: event.target.value }))}
              />
            </Field>
            <Field label="币种">
              <Select
                value={form.currency}
                onChange={(event) => setForm((value) => ({ ...value, currency: event.target.value }))}
              >
                {currencies.data?.map((currency) => (
                  <option key={currency.code} value={currency.code}>
                    {currency.code} · {currency.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="分类">
              <Select
                value={form.category_id}
                onChange={(event) =>
                  setForm((value) => ({ ...value, category_id: event.target.value }))
                }
              >
                <option value="">未分类</option>
                {formCategories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="日期">
              <Input
                type="date"
                value={form.transaction_date}
                onChange={(event) =>
                  setForm((value) => ({ ...value, transaction_date: event.target.value }))
                }
              />
            </Field>
          </div>
          <Field label="描述">
            <Input
              value={form.description}
              placeholder="例如：周末超市采购"
              onChange={(event) =>
                setForm((value) => ({ ...value, description: event.target.value }))
              }
            />
          </Field>
          <Field label="状态" hint="草稿不计入已确认统计口径，可在之后确认。">
            <Select
              value={form.status}
              onChange={(event) =>
                setForm((value) => ({
                  ...value,
                  status: event.target.value as "draft" | "confirmed",
                }))
              }
            >
              <option value="confirmed">已确认</option>
              <option value="draft">草稿</option>
            </Select>
          </Field>

          {create.isError || update.isError ? (
            <ErrorBanner message={errorMessage(create.error ?? update.error)} />
          ) : null}

          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => {
                setModalOpen(false);
                setEditing(null);
              }}
            >
              取消
            </Button>
            <Button
              disabled={!form.account_id || !form.amount || create.isPending || update.isPending}
              onClick={() => {
                if (editing) update.mutate({ id: editing.id, payload: form });
                else create.mutate(form);
              }}
            >
              {create.isPending || update.isPending ? "保存中…" : "保存"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function toIso(value: string): string {
  return value.includes("T") ? value : `${value}T12:00:00`;
}
