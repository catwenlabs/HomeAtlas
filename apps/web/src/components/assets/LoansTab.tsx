import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { accountsApi, currenciesApi, loansApi, type LoanInput } from "../../api/endpoints";
import type { Loan } from "../../api/types";
import { decimalInput, formatDate, money, todayInput } from "../../lib/utils";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Modal,
  Select,
  Spinner,
} from "../ui";

export function LoansTab() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<"" | "active" | "settled">("");
  const [editing, setEditing] = useState<Loan | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [settling, setSettling] = useState<Loan | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["loans", "tab", status],
    queryFn: () => loansApi.list(status ? { status } : {}),
  });
  const items = list.data?.items ?? [];

  const remove = useMutation({
    mutationFn: loansApi.remove,
    onSuccess: invalidate,
    onError: (error) => setActionError(errorText(error)),
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["loans"] });
    queryClient.invalidateQueries({ queryKey: ["assets"] });
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {(
          [
            ["", "全部"],
            ["active", "未结清"],
            ["settled", "已结清"],
          ] as ["" | "active" | "settled", string][]
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setStatus(value)}
            className={`rounded-full border px-3.5 py-1.5 text-sm transition ${
              status === value
                ? "border-primary-500 bg-primary-50 text-primary-700"
                : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
            }`}
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
          登记贷款
        </button>
      </div>

      {actionError ? <ErrorBanner message={actionError} /> : null}

      {list.isLoading ? (
        <Spinner />
      ) : list.isError ? (
        <ErrorBanner message={errorText(list.error)} />
      ) : items.length === 0 ? (
        <EmptyState title="没有贷款" description="登记房贷、车贷等负债后，会自动计入净资产与日利息。" />
      ) : (
        <div className="space-y-3">
          {items.map((loan) => (
            <Card key={loan.id} className="flex flex-wrap items-center gap-3 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium text-slate-900">{loan.name}</p>
                  {loan.institution ? <Badge>{loan.institution}</Badge> : null}
                  {loan.status === "settled" ? (
                    <Badge tone="slate">已结清</Badge>
                  ) : (
                    <Badge tone="red">未结清</Badge>
                  )}
                  {loan.repayment_type === "monthly_interest" ? <Badge>月付息</Badge> : <Badge>到期还本</Badge>}
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  放款 {money(loan.principal, loan.currency)} · 年化{" "}
                  {(Number(loan.annual_rate) * 100).toFixed(2)}% · 起始 {formatDate(loan.start_date)}
                  {loan.due_day ? ` · 每月 ${loan.due_day} 日还款` : ""}
                </p>
              </div>
              <div className="text-right">
                <p className="font-semibold text-slate-900">
                  {money(loan.remaining_principal, loan.currency)}
                </p>
                <p className="text-xs text-slate-500">
                  {loan.status === "active"
                    ? `日利息 ${money(loan.daily_interest ?? 0, loan.currency)}`
                    : loan.settled_date
                      ? `结清于 ${formatDate(loan.settled_date)}`
                      : "已结清"}
                </p>
              </div>
              {loan.status === "active" ? (
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    title="标记结清"
                    className="rounded-lg p-2 text-emerald-600 transition hover:bg-emerald-50"
                    onClick={() => setSettling(loan)}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    title="编辑"
                    className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100"
                    onClick={() => {
                      setEditing(loan);
                      setFormOpen(true);
                    }}
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    title="删除"
                    className="rounded-lg p-2 text-slate-400 transition hover:bg-red-50 hover:text-red-600"
                    onClick={() => {
                      if (window.confirm(`删除贷款「${loan.name}」？`)) remove.mutate(loan.id);
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}

      <LoanFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        loan={editing}
        onSaved={invalidate}
      />
      <SettleModal loan={settling} onClose={() => setSettling(null)} onSaved={invalidate} />
    </div>
  );
}

function LoanFormModal({
  open,
  onClose,
  loan,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  loan: Loan | null;
  onSaved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const currencies = useQuery({
    queryKey: ["currencies"],
    queryFn: () => currenciesApi.list(),
    staleTime: 5 * 60 * 1000,
  });
  const accounts = useQuery({
    queryKey: ["accounts", "options"],
    queryFn: () => accountsApi.list({ page_size: 100, is_active: true }),
    staleTime: 60 * 1000,
  });
  const save = useMutation({
    mutationFn: (payload: LoanInput) =>
      loan ? loansApi.update(loan.id, payload) : loansApi.create(payload),
    onSuccess: () => {
      onSaved();
      onClose();
    },
    onError: (err) => setError(errorText(err)),
  });

  return (
    <Modal open={open} onClose={onClose} title={loan ? "编辑贷款" : "登记贷款"}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          const data = new FormData(event.currentTarget);
          const remaining = String(data.get("remaining_principal") ?? "");
          const payload: LoanInput = {
            name: String(data.get("name") ?? ""),
            institution: String(data.get("institution") ?? "") || null,
            principal: String(data.get("principal") ?? ""),
            currency: String(data.get("currency") ?? "CNY"),
            annual_rate: String(data.get("annual_rate") ?? "0"),
            start_date: String(data.get("start_date") ?? todayInput()),
            end_date: (data.get("end_date") as string) || null,
            due_day: Number(data.get("due_day") ?? "") || null,
            repayment_type: String(data.get("repayment_type") ?? "monthly_interest") as Loan["repayment_type"],
            linked_account_id: String(data.get("linked_account_id") ?? "") || null,
            remark: String(data.get("remark") ?? "") || null,
          };
          if (remaining) payload.remaining_principal = remaining;
          save.mutate(payload);
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="名称">
            <Input name="name" required defaultValue={loan?.name ?? ""} maxLength={100} />
          </Field>
          <Field label="机构（可选）">
            <Input name="institution" defaultValue={loan?.institution ?? ""} maxLength={100} />
          </Field>
          <Field label="放款本金">
            <Input name="principal" required inputMode="decimal" defaultValue={loan ? decimalInput(loan.principal) : ""} />
          </Field>
          <Field label="剩余本金（登记存量贷款可小于放款额）">
            <Input
              name="remaining_principal"
              inputMode="decimal"
              placeholder="默认等于放款本金"
              defaultValue={loan ? decimalInput(loan.remaining_principal) : ""}
            />
          </Field>
          <Field label="币种">
            <Select name="currency" defaultValue={loan?.currency ?? "CNY"}>
              {(currencies.data?.items ?? []).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} {item.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="年利率（如 0.039）">
            <Input name="annual_rate" required inputMode="decimal" defaultValue={loan?.annual_rate ?? ""} />
          </Field>
          <Field label="起借日">
            <Input name="start_date" type="date" required defaultValue={loan?.start_date?.slice(0, 10) ?? todayInput()} />
          </Field>
          <Field label="到期日（可选）">
            <Input name="end_date" type="date" defaultValue={loan?.end_date?.slice(0, 10) ?? ""} />
          </Field>
          <Field label="还款日（每月几号，可选）">
            <Input name="due_day" type="number" min={1} max={31} defaultValue={loan?.due_day ?? ""} />
          </Field>
          <Field label="还款方式">
            <Select name="repayment_type" defaultValue={loan?.repayment_type ?? "monthly_interest"}>
              <option value="monthly_interest">按月付息</option>
              <option value="one_time">到期一次性还本付息</option>
            </Select>
          </Field>
          <Field label="扣款账户（仅提示用，可选）">
            <Select name="linked_account_id" defaultValue={loan?.linked_account_id ?? ""}>
              <option value="">不关联</option>
              {(accounts.data?.items ?? []).map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "保存中…" : "保存"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function SettleModal({
  loan,
  onClose,
  onSaved,
}: {
  loan: Loan | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const settle = useMutation({
    mutationFn: (settled_date: string) => loansApi.settle(loan!.id, settled_date),
    onSuccess: () => {
      onSaved();
      onClose();
    },
    onError: (err) => setError(errorText(err)),
  });
  return (
    <Modal open={loan !== null} onClose={onClose} title={`标记结清 · ${loan?.name ?? ""}`}>
      <p className="text-sm text-slate-600">
        结清后剩余本金清零、负债与日利息立即移出净资产；该操作不可逆（允许提前结清）。
      </p>
      <form
        className="mt-4 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          const data = new FormData(event.currentTarget);
          settle.mutate(String(data.get("settled_date") ?? todayInput()));
        }}
      >
        <Field label="结清日期">
          <Input name="settled_date" type="date" required defaultValue={todayInput()} />
        </Field>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={settle.isPending}>
            {settle.isPending ? "处理中…" : "确认结清"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "操作失败，请稍后重试";
}
