import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";

import { transfersApi } from "../api/endpoints";
import type { Transfer } from "../api/types";
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
import { useAccountNames, useAccounts } from "../hooks/useReference";
import { errorMessage, formatDate, money, todayInput } from "../lib/utils";

const PAGE_SIZE = 20;

interface TransferForm {
  from_account_id: string;
  to_account_id: string;
  from_amount: string;
  to_amount: string;
  exchange_rate: string;
  fee: string;
  transfer_date: string;
  description: string;
  status: "draft" | "confirmed";
}

export function TransfersPage() {
  const queryClient = useQueryClient();
  const accounts = useAccounts();
  const accountNames = useAccountNames();
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<TransferForm>({
    from_account_id: "",
    to_account_id: "",
    from_amount: "",
    to_amount: "",
    exchange_rate: "",
    fee: "0",
    transfer_date: todayInput(),
    description: "",
    status: "confirmed",
  });

  const list = useQuery({
    queryKey: ["transfers", page],
    queryFn: () => transfersApi.list({ page, page_size: PAGE_SIZE }),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["transfers"] });
    await queryClient.invalidateQueries({ queryKey: ["statistics"] });
    await queryClient.invalidateQueries({ queryKey: ["accounts"] });
    await queryClient.invalidateQueries({ queryKey: ["transactions"] });
  };

  const create = useMutation({
    mutationFn: () => {
      const from = accounts.data?.find((item) => item.id === form.from_account_id);
      const to = accounts.data?.find((item) => item.id === form.to_account_id);
      return transfersApi.create({
        from_account_id: form.from_account_id,
        to_account_id: form.to_account_id,
        from_amount: form.from_amount,
        from_currency: from?.currency,
        to_amount: form.to_amount,
        to_currency: to?.currency,
        exchange_rate: form.exchange_rate || undefined,
        fee: form.fee || "0",
        transfer_date: `${form.transfer_date}T12:00:00`,
        description: form.description || null,
        status: form.status,
      });
    },
    onSuccess: async () => {
      setModalOpen(false);
      setMessage("转账已创建");
      await refresh();
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => transfersApi.remove(id),
    onSuccess: async () => {
      setMessage("转账已删除");
      await refresh();
    },
  });

  const reverse = useMutation({
    mutationFn: (id: string) => transfersApi.reverse(id),
    onSuccess: async () => {
      setMessage("已生成转账冲销记录");
      await refresh();
    },
  });

  function openCreate() {
    const first = accounts.data?.[0];
    const second = accounts.data?.[1];
    setEditingId(null);
    setForm({
      from_account_id: first?.id ?? "",
      to_account_id: second?.id ?? "",
      from_amount: "",
      to_amount: "",
      exchange_rate: "",
      fee: "0",
      transfer_date: todayInput(),
      description: "",
      status: "confirmed",
    });
    setModalOpen(true);
  }

  function openEdit(transfer: Transfer) {
    setForm({
      from_account_id: transfer.from_account_id,
      to_account_id: transfer.to_account_id,
      from_amount: transfer.from_amount,
      to_amount: transfer.to_amount,
      exchange_rate: transfer.exchange_rate,
      fee: transfer.fee,
      transfer_date: transfer.transfer_date.slice(0, 10),
      description: transfer.description ?? "",
      status: transfer.status === "draft" ? "draft" : "confirmed",
    });
    setModalOpen(true);
  }

  const update = useMutation({
    mutationFn: (id: string) =>
      transfersApi.update(id, {
        from_account_id: form.from_account_id,
        to_account_id: form.to_account_id,
        from_amount: form.from_amount,
        to_amount: form.to_amount,
        exchange_rate: form.exchange_rate || undefined,
        fee: form.fee || "0",
        transfer_date: `${form.transfer_date}T12:00:00`,
        description: form.description || null,
        status: form.status,
      }),
    onSuccess: async () => {
      setModalOpen(false);
      setMessage("转账已更新");
      await refresh();
    },
  });

  function openEditWithId(transfer: Transfer) {
    setEditingId(transfer.id);
    openEdit(transfer);
  }

  const fromAccount = accounts.data?.find((item) => item.id === form.from_account_id);
  const toAccount = accounts.data?.find((item) => item.id === form.to_account_id);
  const sameCurrency = fromAccount?.currency === toAccount?.currency;
  const mutationError = create.error ?? update.error ?? remove.error ?? reverse.error;
  const totalPages = Math.max(1, Math.ceil((list.data?.total ?? 0) / PAGE_SIZE));

  return (
    <div>
      <PageHeader
        eyebrow="Transfers"
        title="转账"
        description="账户之间的资金划转；跨币种转账可指定换汇金额与汇率。"
        action={
          <Button onClick={openCreate} disabled={!accounts.data?.length}>
            <Plus className="h-4 w-4" />
            新增转账
          </Button>
        }
      />

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
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead>
                  <tr className="border-b border-ink/8 text-xs uppercase tracking-wide text-ink/40">
                    <th className="px-5 py-3 font-medium">日期</th>
                    <th className="px-3 py-3 font-medium">转出 → 转入</th>
                    <th className="px-3 py-3 font-medium">金额</th>
                    <th className="px-3 py-3 font-medium">手续费</th>
                    <th className="px-3 py-3 font-medium">状态</th>
                    <th className="px-5 py-3 text-right font-medium">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink/6">
                  {list.data.items.map((transfer) => (
                    <tr key={transfer.id} className="hover:bg-canvas/40">
                      <td className="whitespace-nowrap px-5 py-3 text-xs text-ink/55">
                        {formatDate(transfer.transfer_date)}
                      </td>
                      <td className="px-3 py-3 text-xs">
                        <span className="flex items-center gap-1.5 text-ink/75">
                          {accountNames.names.get(transfer.from_account_id) ?? "账户"}
                          <ArrowRight className="h-3 w-3 text-ink/30" />
                          {accountNames.names.get(transfer.to_account_id) ?? "账户"}
                        </span>
                        {transfer.description ? (
                          <p className="mt-0.5 truncate text-ink/40">{transfer.description}</p>
                        ) : null}
                      </td>
                      <td className="px-3 py-3 text-xs">
                        <p className="text-ink/80">
                          {money(transfer.from_amount, transfer.from_currency)}
                        </p>
                        {transfer.from_currency !== transfer.to_currency ? (
                          <p className="text-ink/40">
                            → {money(transfer.to_amount, transfer.to_currency)}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-3 py-3 text-xs text-ink/55">
                        {money(transfer.fee, transfer.fee_currency)}
                      </td>
                      <td className="px-3 py-3">
                        <Badge
                          tone={
                            transfer.status === "confirmed"
                              ? "green"
                              : transfer.status === "draft"
                                ? "amber"
                                : "slate"
                          }
                        >
                          {transfer.status === "confirmed"
                            ? "已确认"
                            : transfer.status === "draft"
                              ? "草稿"
                              : "已冲销"}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-right">
                        <div className="flex justify-end gap-1">
                          {transfer.status === "draft" ? (
                            <Button
                              variant="ghost"
                              className="h-8 px-2 text-xs"
                              onClick={() => openEditWithId(transfer)}
                            >
                              编辑
                            </Button>
                          ) : null}
                          {transfer.status === "confirmed" && !transfer.reverses_transfer_id ? (
                            <Button
                              variant="ghost"
                              className="h-8 px-2"
                              title="冲销"
                              onClick={() => {
                                if (window.confirm("确认冲销这笔转账？")) reverse.mutate(transfer.id);
                              }}
                            >
                              <RotateCcw className="h-3.5 w-3.5" />
                            </Button>
                          ) : null}
                          {transfer.status === "draft" ? (
                            <Button
                              variant="ghost"
                              className="h-8 px-2 text-red-600"
                              title="删除"
                              onClick={() => {
                                if (window.confirm("确认删除这笔转账？")) remove.mutate(transfer.id);
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
          <EmptyState title="还没有转账记录" description="在两个账户之间划转资金时创建。" />
        )}
      </Card>

      <Modal
        open={modalOpen}
        title={editingId ? "编辑转账" : "新增转账"}
        onClose={() => {
          setModalOpen(false);
          setEditingId(null);
        }}
      >
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="转出账户">
              <Select
                value={form.from_account_id}
                onChange={(event) =>
                  setForm((value) => ({ ...value, from_account_id: event.target.value }))
                }
              >
                {accounts.data?.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name} · {account.currency}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="转入账户">
              <Select
                value={form.to_account_id}
                onChange={(event) =>
                  setForm((value) => ({ ...value, to_account_id: event.target.value }))
                }
              >
                {accounts.data?.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name} · {account.currency}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={`转出金额${fromAccount ? ` (${fromAccount.currency})` : ""}`}>
              <Input
                type="number"
                step="0.01"
                value={form.from_amount}
                onChange={(event) =>
                  setForm((value) => ({ ...value, from_amount: event.target.value }))
                }
              />
            </Field>
            <Field label={`转入金额${toAccount ? ` (${toAccount.currency})` : ""}`}>
              <Input
                type="number"
                step="0.01"
                value={form.to_amount}
                onChange={(event) =>
                  setForm((value) => ({ ...value, to_amount: event.target.value }))
                }
              />
            </Field>
            <Field label="汇率" hint={sameCurrency ? "同币种可留空" : "跨币种时必填"}>
              <Input
                type="number"
                step="0.000001"
                value={form.exchange_rate}
                onChange={(event) =>
                  setForm((value) => ({ ...value, exchange_rate: event.target.value }))
                }
              />
            </Field>
            <Field label="手续费">
              <Input
                type="number"
                step="0.01"
                value={form.fee}
                onChange={(event) => setForm((value) => ({ ...value, fee: event.target.value }))}
              />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="日期">
              <Input
                type="date"
                value={form.transfer_date}
                onChange={(event) =>
                  setForm((value) => ({ ...value, transfer_date: event.target.value }))
                }
              />
            </Field>
            <Field label="状态">
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
          </div>
          <Field label="描述">
            <Input
              value={form.description}
              onChange={(event) =>
                setForm((value) => ({ ...value, description: event.target.value }))
              }
              placeholder="例如：还信用卡"
            />
          </Field>

          {create.isError || update.isError ? (
            <ErrorBanner message={errorMessage(create.error ?? update.error)} />
          ) : null}

          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => {
                setModalOpen(false);
                setEditingId(null);
              }}
            >
              取消
            </Button>
            <Button
              disabled={
                !form.from_account_id ||
                !form.to_account_id ||
                form.from_account_id === form.to_account_id ||
                !form.from_amount ||
                !form.to_amount ||
                create.isPending ||
                update.isPending
              }
              onClick={() => {
                if (editingId) update.mutate(editingId);
                else create.mutate();
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
