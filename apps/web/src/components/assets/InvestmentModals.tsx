import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import {
  accountsApi,
  currenciesApi,
  investmentTagsApi,
  investmentsApi,
  type FundTransferInput,
  type InvestmentInput,
} from "../../api/endpoints";
import type { Investment } from "../../api/types";
import { decimalInput, money, todayInput } from "../../lib/utils";
import { Button, ErrorBanner, Field, Input, Modal, Select } from "../ui";

const TYPE_OPTIONS: { value: Investment["investment_type"]; label: string }[] = [
  { value: "stock", label: "股票（登记快照，推荐）" },
  { value: "fund", label: "基金" },
  { value: "fixed", label: "定期理财" },
  { value: "daily", label: "活期理财" },
  { value: "cash", label: "现金管理" },
  { value: "bond", label: "债券" },
  { value: "other", label: "其他" },
];

interface InvestmentFormModalProps {
  open: boolean;
  onClose: () => void;
  investment: Investment | null;
  defaultManaged: boolean;
}

export function InvestmentFormModal({
  open,
  onClose,
  investment,
  defaultManaged,
}: InvestmentFormModalProps) {
  const queryClient = useQueryClient();
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
  const tags = useQuery({
    queryKey: ["investment-tags"],
    queryFn: investmentTagsApi.list,
    staleTime: 60 * 1000,
  });

  const [error, setError] = useState<string | null>(null);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  useEffect(() => {
    setSelectedTags(investment?.tag_ids ?? []);
  }, [investment, open]);

  const investmentAccounts = (accounts.data?.items ?? []).filter(
    (account) => account.account_type === "investment",
  );
  const cashAccounts = (accounts.data?.items ?? []).filter(
    (account) => account.account_type !== "investment",
  );

  const save = useMutation({
    mutationFn: (payload: InvestmentInput) =>
      investment ? investmentsApi.update(investment.id, payload) : investmentsApi.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investments"] });
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      queryClient.invalidateQueries({ queryKey: ["investment-tags"] });
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "保存失败，请稍后重试"),
  });

  const isEdit = investment !== null;
  const managed = (investment?.account_id ?? null) !== null;

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? "编辑投资" : "登记投资"}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          const data = new FormData(event.currentTarget);
          const accountId = String(data.get("account_id") ?? "");
          const payload: InvestmentInput = {
            name: String(data.get("name") ?? ""),
            investment_type: String(data.get("investment_type") ?? "stock") as Investment["investment_type"],
            currency: String(data.get("currency") ?? "CNY"),
            start_date: String(data.get("start_date") ?? todayInput()),
            end_date: (data.get("end_date") as string) || null,
            annual_rate: (data.get("annual_rate") as string) || null,
            liquidity: (data.get("liquidity") as string) || null,
            remark: (data.get("remark") as string) || null,
            account_id: accountId || null,
            tag_ids: selectedTags,
          };
          if (!isEdit) {
            payload.principal = String(data.get("principal") ?? "0") || "0";
            const fundAmount = String(data.get("fund_amount") ?? "");
            const fromAccountId = String(data.get("from_account_id") ?? "");
            if (fromAccountId && fundAmount) {
              const fund: FundTransferInput = {
                from_account_id: fromAccountId,
                from_amount: fundAmount,
              };
              const rate = String(data.get("fund_exchange_rate") ?? "");
              if (rate) fund.exchange_rate = rate;
              payload.fund_transfer = fund;
            }
          } else if (!managed) {
            const principal = String(data.get("principal") ?? "");
            if (principal) payload.principal = principal;
          }
          save.mutate(payload);
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="名称">
            <Input name="name" defaultValue={investment?.name ?? ""} required maxLength={100} />
          </Field>
          <Field label="类型">
            <Select name="investment_type" defaultValue={investment?.investment_type ?? "stock"}>
              {TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="币种">
            <Select name="currency" defaultValue={investment?.currency ?? "CNY"}>
              {(currencies.data?.items ?? []).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} {item.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="开始日期">
            <Input
              name="start_date"
              type="date"
              defaultValue={investment?.start_date?.slice(0, 10) ?? todayInput()}
              required
            />
          </Field>
          <Field label="到期日（可选）">
            <Input name="end_date" type="date" defaultValue={investment?.end_date?.slice(0, 10) ?? ""} />
          </Field>
          <Field label="预期年化（可选）">
            <Input
              name="annual_rate"
              inputMode="decimal"
              placeholder="0.03"
              defaultValue={investment?.annual_rate ?? ""}
            />
          </Field>
          <Field label="流动性（可选）">
            <Select name="liquidity" defaultValue={investment?.liquidity ?? ""}>
              <option value="">不指定</option>
              {["T0", "T1", "T2", "T3", "none"].map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={managed ? "托管投资账户" : "托管投资账户（可选，留空 = 独立快照）"}>
            <Select
              name="account_id"
              defaultValue={investment?.account_id ?? ""}
              disabled={isEdit}
            >
              <option value="">不关联（独立快照）</option>
              {investmentAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}（{account.currency}）
                </option>
              ))}
            </Select>
          </Field>
        </div>

        {!isEdit || !managed ? (
          <Field label={managed ? "登记本金（托管型由入金累积，无需填写）" : "投入本金（登记口径）"}>
            <Input
              name="principal"
              inputMode="decimal"
              placeholder="0"
              defaultValue={investment && !managed ? decimalInput(investment.principal) : ""}
              disabled={managed}
            />
          </Field>
        ) : null}

        {isEdit ? null : (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-xs font-medium text-slate-600">
              建仓入金（可选；托管型从现金账户同事务划入）
            </p>
            <div className="mt-2 grid gap-3 sm:grid-cols-3">
              <Field label="从账户">
                <Select name="from_account_id" defaultValue="">
                  <option value="">不划款</option>
                  {cashAccounts.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.name}（{account.currency}）
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="金额">
                <Input name="fund_amount" inputMode="decimal" placeholder="10000" />
              </Field>
              <Field label="汇率（跨币种必填）">
                <Input name="fund_exchange_rate" inputMode="decimal" placeholder="自动 = 1" />
              </Field>
            </div>
            {defaultManaged ? (
              <p className="mt-2 text-xs text-slate-500">
                提示：选择了托管账户但未划款时，本金按上方登记值计。
              </p>
            ) : null}
          </div>
        )}

        <Field label="标签">
          <div className="flex flex-wrap items-center gap-2">
            {(tags.data?.items ?? []).map((tag) => (
              <button
                key={tag.id}
                type="button"
                onClick={() =>
                  setSelectedTags((current) =>
                    current.includes(tag.id)
                      ? current.filter((id) => id !== tag.id)
                      : [...current, tag.id],
                  )
                }
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  selectedTags.includes(tag.id)
                    ? "border-primary-500 bg-primary-50 text-primary-700"
                    : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                }`}
              >
                {tag.name}
              </button>
            ))}
            {(tags.data?.items.length ?? 0) === 0 ? (
              <span className="text-xs text-slate-400">还没有标签，可在下方新建</span>
            ) : null}
            <NewTagInline />
          </div>
        </Field>

        <Field label="备注（可选）">
          <Input name="remark" maxLength={500} defaultValue={investment?.remark ?? ""} />
        </Field>

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

function NewTagInline() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => investmentTagsApi.create({ name }),
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["investment-tags"] });
    },
  });
  return (
    <span className="flex items-center gap-1">
      <Input
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="新标签"
        className="h-8 w-24 text-xs"
        maxLength={50}
      />
      <Button
        type="button"
        variant="secondary"
        className="h-8 px-2.5 text-xs"
        disabled={!name.trim() || create.isPending}
        onClick={() => create.mutate()}
      >
        添加
      </Button>
    </span>
  );
}

interface FundModalProps {
  investment: Investment | null;
  onClose: () => void;
}

export function FundModal({ investment, onClose }: FundModalProps) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const accounts = useQuery({
    queryKey: ["accounts", "options"],
    queryFn: () => accountsApi.list({ page_size: 100, is_active: true }),
    staleTime: 60 * 1000,
  });
  const fund = useMutation({
    mutationFn: (payload: FundTransferInput) =>
      investmentsApi.fund(investment!.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investments"] });
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "入金失败"),
  });

  const cashAccounts = (accounts.data?.items ?? []).filter(
    (account) => account.account_type !== "investment",
  );

  return (
    <Modal open={investment !== null} onClose={onClose} title={`追加入金 · ${investment?.name ?? ""}`}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          const data = new FormData(event.currentTarget);
          const payload: FundTransferInput = {
            from_account_id: String(data.get("from_account_id") ?? ""),
            from_amount: String(data.get("from_amount") ?? ""),
          };
          const rate = String(data.get("exchange_rate") ?? "");
          if (rate) payload.exchange_rate = rate;
          fund.mutate(payload);
        }}
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="从账户">
            <Select name="from_account_id" required defaultValue="">
              <option value="" disabled>
                选择现金账户
              </option>
              {cashAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}（{account.currency}）
                </option>
              ))}
            </Select>
          </Field>
          <Field label={`金额（投资币种 ${investment?.currency ?? ""}）`}>
            <Input name="from_amount" inputMode="decimal" required placeholder="10000" />
          </Field>
          <Field label="汇率（跨币种必填）">
            <Input name="exchange_rate" inputMode="decimal" placeholder="同币种留空" />
          </Field>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={fund.isPending}>
            {fund.isPending ? "入金中…" : "确认入金"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface RedeemModalProps {
  investment: Investment | null;
  onClose: () => void;
}

export function RedeemModal({ investment, onClose }: RedeemModalProps) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const accounts = useQuery({
    queryKey: ["accounts", "options"],
    queryFn: () => accountsApi.list({ page_size: 100, is_active: true }),
    staleTime: 60 * 1000,
  });
  const redeem = useMutation({
    mutationFn: (payload: { to_account_id: string; to_amount: string }) =>
      investmentsApi.redeem(investment!.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investments"] });
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "赎回失败"),
  });

  const sameCurrency = (accounts.data?.items ?? []).filter(
    (account) =>
      account.account_type !== "investment" && account.currency === investment?.currency,
  );

  return (
    <Modal open={investment !== null} onClose={onClose} title={`全额赎回 · ${investment?.name ?? ""}`}>
      <p className="text-sm text-slate-600">
        本金 {money(investment?.principal, investment?.currency)}；回款账户需与投资同币种。
        赎回金额低于本金即确认投资亏损，高于本金生成投资收益。
      </p>
      <form
        className="mt-4 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          const data = new FormData(event.currentTarget);
          redeem.mutate({
            to_account_id: String(data.get("to_account_id") ?? ""),
            to_amount: String(data.get("to_amount") ?? ""),
          });
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="回款账户">
            <Select name="to_account_id" required defaultValue="">
              <option value="" disabled>
                选择账户
              </option>
              {sameCurrency.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}（{account.currency}）
                </option>
              ))}
            </Select>
          </Field>
          <Field label="赎回金额">
            <Input
              name="to_amount"
              inputMode="decimal"
              required
              defaultValue={decimalInput(investment?.principal)}
            />
          </Field>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={redeem.isPending}>
            {redeem.isPending ? "赎回中…" : "确认赎回"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
