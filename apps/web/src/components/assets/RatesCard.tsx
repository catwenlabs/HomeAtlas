import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";

import { exchangeRatesApi } from "../../api/endpoints";
import { currenciesApi } from "../../api/endpoints";
import { ApiError } from "../../api/client";
import {
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Select,
  Spinner,
} from "../ui";
import { errorMessage, formatDate, todayInput } from "../../lib/utils";

export function RatesCard() {
  const queryClient = useQueryClient();
  const rates = useQuery({
    queryKey: ["exchange-rates", "recent"],
    queryFn: () => exchangeRatesApi.list(),
  });
  const currencies = useQuery({
    queryKey: ["currencies"],
    queryFn: () => currenciesApi.list(),
    staleTime: 5 * 60 * 1000,
  });

  const create = useMutation({
    mutationFn: exchangeRatesApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-rates"] });
      queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
  });
  const remove = useMutation({
    mutationFn: exchangeRatesApi.remove,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-rates"] });
      queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
  });

  const codes = (currencies.data?.items ?? []).map((item) => item.code);

  return (
    <Card className="p-5">
      <CardHeader
        title="汇率"
        description="家庭记账视角的手工报价；快照与总览折算依赖这里的最新价（反向币对自动换算）。"
      />

      <form
        className="mt-4 grid gap-3 sm:grid-cols-5"
        onSubmit={(event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const data = new FormData(form);
          const base = String(data.get("base") ?? "");
          const quote = String(data.get("quote") ?? "");
          const rate = String(data.get("rate") ?? "");
          const rate_date = String(data.get("rate_date") ?? todayInput());
          if (!base || !quote || !rate || base === quote) return;
          create.mutate(
            { base_currency: base, quote_currency: quote, rate, rate_date },
            {
              onSuccess: () => {
                form.reset();
              },
            },
          );
        }}
      >
        <Field label="基准币">
          <Select name="base" defaultValue="USD" required>
            {codes.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="目标币">
          <Select name="quote" defaultValue="CNY" required>
            {codes.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="汇率">
          <Input name="rate" placeholder="7.20" required inputMode="decimal" />
        </Field>
        <Field label="日期">
          <Input name="rate_date" type="date" defaultValue={todayInput()} required />
        </Field>
        <div className="flex items-end">
          <button
            type="submit"
            className="w-full rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50"
            disabled={create.isPending}
          >
            {create.isPending ? "保存中…" : "添加汇率"}
          </button>
        </div>
      </form>

      {create.isError ? <ErrorBanner message={errorMessage(create.error)} /> : null}

      <div className="mt-4">
        {rates.isLoading ? (
          <Spinner />
        ) : rates.isError ? (
          <ErrorBanner message={errorMessage(rates.error)} />
        ) : (rates.data?.items ?? []).length === 0 ? (
          <EmptyState
            title="还没有汇率"
            description="单币种家庭不需要；多币种资产录入上方币对后，总览与快照即可折算。"
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {(rates.data?.items ?? []).map((rate) => (
              <li key={rate.id} className="flex items-center justify-between py-2.5">
                <div>
                  <p className="text-sm font-medium text-slate-900">
                    {rate.base_currency} / {rate.quote_currency}
                  </p>
                  <p className="text-xs text-slate-500">{formatDate(rate.rate_date)}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm text-slate-700">{rate.rate}</span>
                  <button
                    type="button"
                    aria-label="删除汇率"
                    className="rounded-lg p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-600"
                    onClick={() => {
                      if (
                        window.confirm(
                          `删除 ${rate.base_currency}/${rate.quote_currency} ${formatDate(rate.rate_date)} 的汇率？`,
                        )
                      ) {
                        remove.mutate(rate.id);
                      }
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {remove.isError ? (
          <p className="mt-2 text-xs text-red-600">
            {remove.error instanceof ApiError ? remove.error.message : errorMessage(remove.error)}
          </p>
        ) : null}
      </div>
    </Card>
  );
}
