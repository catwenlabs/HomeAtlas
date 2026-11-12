import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight, Check, Info, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { setupApi } from "../api/endpoints";
import type { SetupCategoryPayload } from "../api/types";
import { Badge, Button, Card, ErrorBanner, Field, Input, Label, Select, Spinner } from "../components/ui";
import { errorMessage } from "../lib/utils";
import { useAuth } from "../store/auth";
import { useSetup } from "../store/setup";

const STEPS = ["管理员账户", "家庭与币种", "基础数据"] as const;

export function SetupPage() {
  const navigate = useNavigate();
  const setSession = useAuth((state) => state.setSession);
  const refreshSetup = useSetup((state) => state.refresh);

  const optionsQuery = useQuery({
    queryKey: ["setup-options"],
    queryFn: setupApi.options,
  });

  const [step, setStep] = useState(0);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [householdName, setHouseholdName] = useState("我的家庭");
  const [baseCurrency, setBaseCurrency] = useState("CNY");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [selectedCurrencies, setSelectedCurrencies] = useState<Set<string>>(new Set());
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set());
  const [customCategories, setCustomCategories] = useState<SetupCategoryPayload[]>([]);
  const [customName, setCustomName] = useState("");
  const [customType, setCustomType] = useState<"expense" | "income">("expense");
  const [localError, setLocalError] = useState<string | null>(null);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    const options = optionsQuery.data;
    if (!options || initialized) return;
    setSelectedCurrencies(new Set(options.currencies.map((item) => item.code)));
    setSelectedCategories(new Set(options.categories.map(categoryKey)));
    setInitialized(true);
  }, [optionsQuery.data, initialized]);

  const options = optionsQuery.data;
  const categoryOptions = useMemo(() => options?.categories ?? [], [options]);

  const submit = useMutation({
    mutationFn: () =>
      setupApi.complete({
        username,
        password,
        display_name: displayName.trim() || undefined,
        household_name: householdName.trim() || "我的家庭",
        base_currency: baseCurrency,
        timezone,
        currency_codes: [...selectedCurrencies],
        categories: [
          ...categoryOptions.filter((item) => selectedCategories.has(categoryKey(item))),
          ...customCategories,
        ],
      }),
    onSuccess: async (session) => {
      setSession(session);
      await refreshSetup();
      await navigate({ to: "/" });
    },
  });

  function next() {
    setLocalError(null);
    if (step === 0) {
      if (username.trim().length < 3) return setLocalError("用户名至少 3 个字符");
      if (!/^[A-Za-z0-9_.-]+$/.test(username.trim())) {
        return setLocalError("用户名只能包含字母、数字、下划线、点和短横线");
      }
      if (password.length < 8) return setLocalError("密码至少 8 个字符");
      if (password !== confirmPassword) return setLocalError("两次输入的密码不一致");
    }
    if (step === 1) {
      if (!selectedCurrencies.size) return setLocalError("请至少选择一个币种");
      if (!selectedCurrencies.has(baseCurrency)) {
        return setLocalError("本位币必须包含在已选币种中");
      }
    }
    setStep((value) => Math.min(value + 1, STEPS.length - 1));
  }

  function toggleCurrency(code: string) {
    setSelectedCurrencies((value) => {
      const nextValue = new Set(value);
      if (nextValue.has(code)) {
        nextValue.delete(code);
        if (code === baseCurrency) {
          const fallback = [...nextValue][0];
          if (fallback) setBaseCurrency(fallback);
        }
      } else {
        nextValue.add(code);
      }
      return nextValue;
    });
  }

  function toggleCategory(key: string) {
    setSelectedCategories((value) => {
      const nextValue = new Set(value);
      if (nextValue.has(key)) nextValue.delete(key);
      else nextValue.add(key);
      return nextValue;
    });
  }

  function addCustomCategory() {
    const name = customName.trim();
    if (!name) return;
    const duplicate =
      categoryOptions.some(
        (item) => item.name === name && item.category_type === customType,
      ) ||
      customCategories.some(
        (item) => item.name === name && item.category_type === customType,
      );
    if (duplicate) {
      setLocalError("同一类型下已存在同名分类");
      return;
    }
    const sortOrder = 1000 + customCategories.length;
    setCustomCategories((value) => [
      ...value,
      { name, category_type: customType, sort_order: sortOrder },
    ]);
    setCustomName("");
    setLocalError(null);
  }

  if (optionsQuery.isLoading) {
    return (
      <div className="mx-auto max-w-3xl py-20">
        <Spinner label="正在读取初始化选项…" />
      </div>
    );
  }

  if (optionsQuery.isError) {
    return (
      <div className="mx-auto max-w-3xl py-20">
        <ErrorBanner message={errorMessage(optionsQuery.error)} />
      </div>
    );
  }

  const errors = [localError, submit.isError ? errorMessage(submit.error) : null].filter(
    Boolean,
  ) as string[];
  const selectedCategoryCount = selectedCategories.size + customCategories.length;

  return (
    <div className="mx-auto max-w-3xl py-8">
      <div className="mb-8">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary-700">
          First run · 首次部署
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">
          欢迎使用 HomeAtlas
        </h1>
        <p className="mt-2 max-w-xl text-sm text-ink/55">
          数据库还没有任何账户。下面三步只会在你确认后写入数据；内置币种与分类仅作为预填项，你可以按需增减。
        </p>
      </div>

      <ol className="mb-6 flex items-center gap-2 text-xs">
        {STEPS.map((label, index) => (
          <li key={label} className="flex items-center gap-2">
            <span
              className={`grid h-6 w-6 place-items-center rounded-full text-[11px] font-semibold ${
                index <= step
                  ? "bg-primary-600 text-white"
                  : "bg-ink/8 text-ink/40"
              }`}
            >
              {index < step ? <Check className="h-3.5 w-3.5" /> : index + 1}
            </span>
            <span className={index <= step ? "text-ink" : "text-ink/40"}>{label}</span>
            {index < STEPS.length - 1 ? <span className="mx-1 h-px w-6 bg-ink/15" /> : null}
          </li>
        ))}
      </ol>

      <Card className="p-6">
        {step === 0 ? (
          <div className="space-y-4">
            <div>
              <h2 className="text-base font-semibold text-ink">创建家庭管理员</h2>
              <p className="mt-1 text-xs text-ink/50">
                该账户拥有家庭的全部管理权限，之后可在设置页添加其他成员。
              </p>
            </div>
            <Field label="用户名">
              <Input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="例如 owner"
                autoComplete="username"
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="密码" hint="至少 8 个字符">
                <Input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="new-password"
                />
              </Field>
              <Field label="确认密码">
                <Input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  autoComplete="new-password"
                />
              </Field>
            </div>
            <Field label="显示名称" hint="可选，默认与用户名一致">
              <Input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="例如 家里的账本"
              />
            </Field>
          </div>
        ) : null}

        {step === 1 ? (
          <div className="space-y-5">
            <div>
              <h2 className="text-base font-semibold text-ink">家庭信息与币种</h2>
              <p className="mt-1 text-xs text-ink/50">
                家庭是账本的数据边界；所有收支都以本位币汇总统计。
              </p>
            </div>
            <Field label="家庭名称">
              <Input
                value={householdName}
                onChange={(event) => setHouseholdName(event.target.value)}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="本位币">
                <Select
                  value={baseCurrency}
                  onChange={(event) => {
                    setBaseCurrency(event.target.value);
                    setSelectedCurrencies((value) => new Set(value).add(event.target.value));
                  }}
                >
                  {options?.currencies
                    .filter((item) => selectedCurrencies.has(item.code))
                    .map((item) => (
                      <option key={item.code} value={item.code}>
                        {item.code} · {item.name}
                      </option>
                    ))}
                </Select>
              </Field>
              <Field label="时区">
                <Select value={timezone} onChange={(event) => setTimezone(event.target.value)}>
                  {options?.timezones.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <div>
              <Label>启用的币种</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {options?.currencies.map((item) => {
                  const checked = selectedCurrencies.has(item.code);
                  return (
                    <button
                      key={item.code}
                      type="button"
                      onClick={() => toggleCurrency(item.code)}
                      className={`flex items-center justify-between rounded-xl border px-3 py-2.5 text-left text-sm transition ${
                        checked
                          ? "border-primary-300 bg-primary-50 text-primary-900"
                          : "border-ink/10 bg-white text-ink/60 hover:border-ink/25"
                      }`}
                    >
                      <span>
                        <span className="font-medium">{item.code}</span>
                        <span className="ml-2 text-xs text-ink/50">
                          {item.name} {item.symbol}
                        </span>
                      </span>
                      <span
                        className={`grid h-4 w-4 place-items-center rounded border ${
                          checked ? "border-primary-600 bg-primary-600 text-white" : "border-ink/20"
                        }`}
                      >
                        {checked ? <Check className="h-3 w-3" /> : null}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 flex items-start gap-1.5 text-xs text-ink/45">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                未勾选的币种不会写入数据库，之后需要时可由管理员手动添加。
              </p>
            </div>
          </div>
        ) : null}

        {step === 2 ? (
          <div className="space-y-5">
            <div>
              <h2 className="text-base font-semibold text-ink">确认基础数据</h2>
              <p className="mt-1 text-xs text-ink/50">
                已预选内置分类，取消勾选即可不创建；也可以补充自定义分类。
              </p>
            </div>

            {(["income", "expense"] as const).map((type) => (
              <div key={type}>
                <div className="mb-2 flex items-center gap-2">
                  <Label className="mb-0">{type === "income" ? "收入分类" : "支出分类"}</Label>
                  <Badge tone={type === "income" ? "green" : "red"}>
                    {categoryOptions.filter((item) => item.category_type === type).length} 项
                  </Badge>
                </div>
                <div className="flex flex-wrap gap-2">
                  {categoryOptions
                    .filter((item) => item.category_type === type)
                    .map((item) => {
                      const key = categoryKey(item);
                      const checked = selectedCategories.has(key);
                      return (
                        <button
                          key={key}
                          type="button"
                          onClick={() => toggleCategory(key)}
                          className={`rounded-full border px-3 py-1.5 text-xs transition ${
                            checked
                              ? "border-primary-300 bg-primary-50 text-primary-800"
                              : "border-ink/10 bg-white text-ink/45"
                          }`}
                        >
                          {checked ? "✓ " : ""}
                          {item.name}
                        </button>
                      );
                    })}
                </div>
              </div>
            ))}

            <div className="rounded-2xl border border-dashed border-ink/15 p-4">
              <Label>添加自定义分类</Label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  value={customName}
                  onChange={(event) => setCustomName(event.target.value)}
                  placeholder="例如 宠物"
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addCustomCategory();
                    }
                  }}
                />
                <Select
                  className="sm:w-32"
                  value={customType}
                  onChange={(event) => setCustomType(event.target.value as "income" | "expense")}
                >
                  <option value="expense">支出</option>
                  <option value="income">收入</option>
                </Select>
                <Button variant="outline" onClick={addCustomCategory} className="sm:w-auto">
                  <Plus className="h-4 w-4" />
                  添加
                </Button>
              </div>
              {customCategories.length ? (
                <ul className="mt-3 flex flex-wrap gap-2">
                  {customCategories.map((item, index) => (
                    <li
                      key={`${item.category_type}-${item.name}-${index}`}
                      className="flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800"
                    >
                      {item.name}
                      <span className="text-amber-500">
                        {item.category_type === "income" ? "收入" : "支出"}
                      </span>
                      <button
                        type="button"
                        aria-label={`删除 ${item.name}`}
                        onClick={() =>
                          setCustomCategories((value) =>
                            value.filter((_, itemIndex) => itemIndex !== index),
                          )
                        }
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>

            <div className="rounded-2xl bg-canvas/70 p-4 text-sm text-ink/65">
              <p>
                将创建：<strong className="text-ink">{selectedCurrencies.size}</strong> 个币种、
                <strong className="text-ink"> {selectedCategoryCount} </strong> 个分类、
                <strong className="text-ink"> 1 </strong> 个家庭与 1 名管理员。
              </p>
              <p className="mt-1 text-xs text-ink/45">
                点击“完成初始化”后才会写入数据库，此操作只可执行一次。
              </p>
            </div>
          </div>
        ) : null}

        {errors.length ? (
          <div className="mt-4 space-y-2">
            {errors.map((message) => (
              <ErrorBanner key={message} message={message} />
            ))}
          </div>
        ) : null}

        <div className="mt-6 flex items-center justify-between border-t border-ink/8 pt-5">
          <Button
            variant="ghost"
            onClick={() => setStep((value) => Math.max(0, value - 1))}
            disabled={step === 0 || submit.isPending}
          >
            <ArrowLeft className="h-4 w-4" />
            上一步
          </Button>
          {step < STEPS.length - 1 ? (
            <Button onClick={next}>
              下一步
              <ArrowRight className="h-4 w-4" />
            </Button>
          ) : (
            <Button onClick={() => submit.mutate()} disabled={submit.isPending}>
              {submit.isPending ? "正在初始化…" : "完成初始化"}
              <Check className="h-4 w-4" />
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}

function categoryKey(item: { name: string; category_type: string }): string {
  return `${item.category_type}:${item.name}`;
}
