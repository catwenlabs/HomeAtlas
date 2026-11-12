import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Landmark, Pencil, Plus, Scale, Trash2, Wallet } from "lucide-react";
import { useState } from "react";

import { accountsApi, statisticsApi } from "../api/endpoints";
import type { Account } from "../api/types";
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
import { useCurrencies } from "../hooks/useReference";
import { errorMessage, money, todayInput } from "../lib/utils";
import { useAuth } from "../store/auth";

const ACCOUNT_TYPES = [
  { value: "bank", label: "银行卡" },
  { value: "cash", label: "现金" },
  { value: "wallet", label: "电子钱包" },
  { value: "other", label: "其他" },
];

interface AccountForm {
  name: string;
  institution: string;
  account_type: string;
  currency: string;
  is_active: boolean;
}

export function AccountsPage() {
  const queryClient = useQueryClient();
  const household = useAuth((state) => state.household);
  const currencies = useCurrencies();
  const [message, setMessage] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [form, setForm] = useState<AccountForm>({
    name: "",
    institution: "",
    account_type: "bank",
    currency: household?.base_currency ?? "CNY",
    is_active: true,
  });
  const [balanceAccount, setBalanceAccount] = useState<Account | null>(null);
  const [balanceForm, setBalanceForm] = useState({ amount: "", currency: "", date: todayInput() });

  const accounts = useQuery({
    queryKey: ["accounts", true],
    queryFn: () => accountsApi.list({ page_size: 100 }),
    select: (page) => page.items,
  });
  const balances = useQuery({
    queryKey: ["statistics", "account-balances"],
    queryFn: statisticsApi.accountBalances,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["accounts"] });
    await queryClient.invalidateQueries({ queryKey: ["statistics"] });
    await queryClient.invalidateQueries({ queryKey: ["transactions"] });
  };

  const create = useMutation({
    mutationFn: () =>
      accountsApi.create({
        name: form.name.trim(),
        institution: form.institution.trim() || null,
        account_type: form.account_type,
        currency: form.currency,
      }),
    onSuccess: async () => {
      setModalOpen(false);
      setMessage("账户已创建");
      await refresh();
    },
  });

  const update = useMutation({
    mutationFn: () =>
      accountsApi.update(editing!.id, {
        name: form.name.trim(),
        institution: form.institution.trim() || null,
        account_type: form.account_type,
        currency: form.currency,
        is_active: form.is_active,
      }),
    onSuccess: async () => {
      setModalOpen(false);
      setEditing(null);
      setMessage("账户已更新");
      await refresh();
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => accountsApi.remove(id),
    onSuccess: async () => {
      setMessage("账户已删除");
      await refresh();
    },
  });

  const openingBalance = useMutation({
    mutationFn: () =>
      accountsApi.setOpeningBalance(balanceAccount!.id, {
        amount: balanceForm.amount,
        currency: balanceForm.currency || undefined,
        transaction_date: `${balanceForm.date}T12:00:00`,
      }),
    onSuccess: async () => {
      setBalanceAccount(null);
      setMessage("期初余额已更新");
      await refresh();
    },
  });

  function openCreate() {
    setEditing(null);
    setForm({
      name: "",
      institution: "",
      account_type: "bank",
      currency: household?.base_currency ?? "CNY",
      is_active: true,
    });
    setModalOpen(true);
  }

  function openEdit(account: Account) {
    setEditing(account);
    setForm({
      name: account.name,
      institution: account.institution ?? "",
      account_type: account.account_type,
      currency: account.currency,
      is_active: account.is_active,
    });
    setModalOpen(true);
  }

  function openBalance(account: Account) {
    const existing = balances.data?.accounts.find((item) => item.account_id === account.id);
    const first = existing?.balances[0];
    setBalanceAccount(account);
    setBalanceForm({
      amount: first?.book_balance ?? "",
      currency: first?.currency ?? account.currency,
      date: todayInput(),
    });
  }

  const mutationError = create.error ?? update.error ?? remove.error ?? openingBalance.error;
  const balanceMap = new Map(
    (balances.data?.accounts ?? []).map((item) => [item.account_id, item.balances]),
  );

  return (
    <div>
      <PageHeader
        eyebrow="Accounts"
        title="账户"
        description="银行卡、现金与电子钱包；每个账户保留自己的记账币种。"
        action={
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4" />
            新增账户
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

      {accounts.isLoading ? (
        <Spinner />
      ) : accounts.isError ? (
        <ErrorBanner message={errorMessage(accounts.error)} />
      ) : accounts.data?.length ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {accounts.data.map((account) => {
            const lines = balanceMap.get(account.id) ?? [];
            return (
              <Card key={account.id} className="flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="grid h-10 w-10 place-items-center rounded-2xl bg-primary-50 text-primary-700">
                      {account.account_type === "cash" ? (
                        <Wallet className="h-4 w-4" />
                      ) : (
                        <Landmark className="h-4 w-4" />
                      )}
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-ink">{account.name}</p>
                      <p className="text-xs text-ink/45">
                        {ACCOUNT_TYPES.find((item) => item.value === account.account_type)?.label ??
                          account.account_type}
                        {account.institution ? ` · ${account.institution}` : ""}
                      </p>
                    </div>
                  </div>
                  <Badge tone={account.is_active ? "green" : "slate"}>
                    {account.is_active ? "启用" : "停用"}
                  </Badge>
                </div>

                <div className="mt-4 flex-1 rounded-xl bg-canvas/60 p-3">
                  {lines.length ? (
                    <ul className="space-y-1">
                      {lines.map((line) => (
                        <li key={line.currency} className="flex items-center justify-between text-sm">
                          <span className="text-xs text-ink/50">{line.currency}</span>
                          <span className="font-medium text-ink">
                            {money(line.book_balance, line.currency)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-ink/45">暂无余额，先设置期初余额或记账。</p>
                  )}
                </div>

                <div className="mt-4 flex flex-wrap gap-1.5">
                  <Button variant="outline" className="h-8 px-2.5 text-xs" onClick={() => openBalance(account)}>
                    <Scale className="h-3.5 w-3.5" />
                    期初余额
                  </Button>
                  <Button variant="ghost" className="h-8 px-2.5 text-xs" onClick={() => openEdit(account)}>
                    <Pencil className="h-3.5 w-3.5" />
                    编辑
                  </Button>
                  <Button
                    variant="ghost"
                    className="h-8 px-2.5 text-xs text-red-600"
                    onClick={() => {
                      if (window.confirm(`确认删除账户「${account.name}」？`)) remove.mutate(account.id);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    删除
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        <Card>
          <EmptyState title="还没有账户" description="创建第一个账户，开始记录家庭收支。" />
        </Card>
      )}

      <Modal
        open={modalOpen}
        title={editing ? "编辑账户" : "新增账户"}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
      >
        <div className="space-y-4">
          <Field label="账户名称">
            <Input
              value={form.name}
              onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
              placeholder="例如 工资卡"
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="账户类型">
              <Select
                value={form.account_type}
                onChange={(event) =>
                  setForm((value) => ({ ...value, account_type: event.target.value }))
                }
              >
                {ACCOUNT_TYPES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="记账币种">
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
          </div>
          <Field label="开户机构" hint="可选">
            <Input
              value={form.institution}
              onChange={(event) => setForm((value) => ({ ...value, institution: event.target.value }))}
              placeholder="例如 招商银行"
            />
          </Field>
          {editing ? (
            <Field label="状态">
              <Select
                value={form.is_active ? "active" : "inactive"}
                onChange={(event) =>
                  setForm((value) => ({ ...value, is_active: event.target.value === "active" }))
                }
              >
                <option value="active">启用</option>
                <option value="inactive">停用</option>
              </Select>
            </Field>
          ) : null}

          {create.isError || update.isError ? (
            <ErrorBanner message={errorMessage(create.error ?? update.error)} />
          ) : null}

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              取消
            </Button>
            <Button
              disabled={!form.name.trim() || create.isPending || update.isPending}
              onClick={() => (editing ? update.mutate() : create.mutate())}
            >
              {create.isPending || update.isPending ? "保存中…" : "保存"}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={Boolean(balanceAccount)}
        title={`设置期初余额 · ${balanceAccount?.name ?? ""}`}
        onClose={() => setBalanceAccount(null)}
      >
        <div className="space-y-4">
          <p className="text-xs text-ink/50">
            期初余额会生成一笔“期初余额”类型记录；重复设置会覆盖同一账户同一币种的期初记录。
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="金额">
              <Input
                type="number"
                step="0.01"
                value={balanceForm.amount}
                onChange={(event) =>
                  setBalanceForm((value) => ({ ...value, amount: event.target.value }))
                }
              />
            </Field>
            <Field label="币种">
              <Select
                value={balanceForm.currency}
                onChange={(event) =>
                  setBalanceForm((value) => ({ ...value, currency: event.target.value }))
                }
              >
                {currencies.data?.map((currency) => (
                  <option key={currency.code} value={currency.code}>
                    {currency.code} · {currency.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="日期">
            <Input
              type="date"
              value={balanceForm.date}
              onChange={(event) =>
                setBalanceForm((value) => ({ ...value, date: event.target.value }))
              }
            />
          </Field>
          {openingBalance.isError ? (
            <ErrorBanner message={errorMessage(openingBalance.error)} />
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setBalanceAccount(null)}>
              取消
            </Button>
            <Button
              disabled={!balanceForm.amount || openingBalance.isPending}
              onClick={() => openingBalance.mutate()}
            >
              {openingBalance.isPending ? "保存中…" : "保存"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
