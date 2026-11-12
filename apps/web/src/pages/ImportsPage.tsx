import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, RefreshCw, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { importsApi, type ImportMappingInput } from "../api/endpoints";
import type { ImportRow } from "../api/types";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  PageHeader,
  Select,
  Spinner,
  SuccessBanner,
} from "../components/ui";
import { useAccounts } from "../hooks/useReference";
import { errorMessage, formatDate } from "../lib/utils";

const PAGE_SIZE = 20;
const STATUS_LABELS: Record<string, string> = {
  uploaded: "待映射",
  mapped: "已映射",
  previewed: "待确认",
  completed: "已完成",
  partial: "部分完成",
  cancelled: "已取消",
  failed: "失败",
};

const MAPPING_FIELDS: { key: keyof ImportMappingInput["columns"]; label: string }[] = [
  { key: "transaction_date", label: "交易日期 *" },
  { key: "amount", label: "金额" },
  { key: "direction", label: "收支方向" },
  { key: "debit", label: "支出列" },
  { key: "credit", label: "收入列" },
  { key: "description", label: "描述" },
  { key: "category", label: "分类" },
  { key: "currency", label: "币种" },
  { key: "external_id", label: "外部单号" },
];

export function ImportsPage() {
  const queryClient = useQueryClient();
  const accounts = useAccounts();
  const [page, setPage] = useState(1);
  const [accountId, setAccountId] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const list = useQuery({
    queryKey: ["imports", page],
    queryFn: () => importsApi.list({ page, page_size: PAGE_SIZE }),
  });

  const upload = useMutation({
    mutationFn: (file: File) => importsApi.upload(file, accountId || undefined),
    onSuccess: async (batch) => {
      setSelectedId(batch.id);
      setMessage("文件已上传，请确认字段映射。");
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => importsApi.remove(id),
    onSuccess: async () => {
      setSelectedId(null);
      setMessage("导入批次已删除");
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
  });

  async function downloadTemplate(format: "csv" | "xlsx") {
    try {
      const blob = await importsApi.downloadTemplate(format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `homeatlas-import-template.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(errorMessage(error));
    }
  }

  const totalPages = Math.max(1, Math.ceil((list.data?.total ?? 0) / PAGE_SIZE));

  return (
    <div>
      <PageHeader
        eyebrow="Imports"
        title="账单导入"
        description="上传 CSV 或 Excel，先映射字段并预览，确认后才写入正式收支。"
        action={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => downloadTemplate("csv")}>
              <Download className="h-4 w-4" />
              CSV 模板
            </Button>
            <Button variant="outline" onClick={() => downloadTemplate("xlsx")}>
              <Download className="h-4 w-4" />
              XLSX 模板
            </Button>
          </div>
        }
      />

      {message ? (
        <div className="mb-4">
          <SuccessBanner message={message} />
        </div>
      ) : null}
      {upload.isError ? (
        <div className="mb-4">
          <ErrorBanner message={errorMessage(upload.error)} />
        </div>
      ) : null}

      <Card className="mb-4 p-5">
        <div className="grid gap-4 lg:grid-cols-[1fr_220px_auto] lg:items-end">
          <div>
            <p className="text-sm font-semibold text-ink">上传账单文件</p>
            <p className="mt-1 text-xs text-ink/45">支持 .csv / .txt / .xlsx / .xlsm，单文件大小受限。</p>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.txt,.xlsx,.xlsm"
              className="mt-3 block w-full cursor-pointer rounded-xl border border-dashed border-ink/20 bg-canvas/40 px-3 py-3 text-xs text-ink/55 file:mr-3 file:rounded-lg file:border-0 file:bg-primary-600 file:px-3 file:py-1.5 file:text-xs file:text-white"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) upload.mutate(file);
                event.target.value = "";
              }}
            />
          </div>
          <Field label="默认账户" hint="可留空，确认时逐行映射">
            <Select value={accountId} onChange={(event) => setAccountId(event.target.value)}>
              <option value="">不指定</option>
              {accounts.data?.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </Select>
          </Field>
          <Button onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
            <Upload className="h-4 w-4" />
            {upload.isPending ? "上传中…" : "选择文件"}
          </Button>
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
        <Card>
          <CardHeader
            title="导入批次"
            description={`${list.data?.total ?? 0} 个批次`}
            action={
              <Button
                variant="ghost"
                className="h-8 px-2"
                onClick={() => queryClient.invalidateQueries({ queryKey: ["imports"] })}
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            }
          />
          {list.isLoading ? (
            <Spinner />
          ) : list.isError ? (
            <div className="p-5">
              <ErrorBanner message={errorMessage(list.error)} />
            </div>
          ) : list.data && list.data.items.length ? (
            <>
              <ul className="max-h-[540px] divide-y divide-ink/6 overflow-y-auto">
                {list.data.items.map((batch) => (
                  <li key={batch.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(batch.id)}
                      className={`w-full px-4 py-3 text-left transition hover:bg-canvas/50 ${
                        selectedId === batch.id ? "bg-primary-50/60" : ""
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium text-ink">
                          {batch.original_filename ?? "未命名文件"}
                        </span>
                        <Badge tone={statusTone(batch.status)}>
                          {STATUS_LABELS[batch.status] ?? batch.status}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs text-ink/40">
                        {formatDate(batch.created_at)} · {batch.total_rows} 行 · 有效{" "}
                        {batch.valid_rows}
                        {batch.imported_rows ? ` · 已导入 ${batch.imported_rows}` : ""}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex items-center justify-between border-t border-ink/8 px-4 py-2.5 text-xs text-ink/45">
                <span>
                  第 {list.data.page} / {totalPages} 页
                </span>
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    className="h-7 px-2 text-xs"
                    disabled={page <= 1}
                    onClick={() => setPage((value) => value - 1)}
                  >
                    上一页
                  </Button>
                  <Button
                    variant="ghost"
                    className="h-7 px-2 text-xs"
                    disabled={page >= totalPages}
                    onClick={() => setPage((value) => value + 1)}
                  >
                    下一页
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <EmptyState title="还没有导入记录" description="上传账单文件开始第一次导入。" />
          )}
        </Card>

        {selectedId ? (
          <ImportDetail
            batchId={selectedId}
            onClose={() => setSelectedId(null)}
            onDelete={() => remove.mutate(selectedId)}
            onMessage={setMessage}
          />
        ) : (
          <Card>
            <EmptyState
              title="选择一个批次"
              description="在左侧选择批次，完成字段映射、预览并确认导入。"
            />
          </Card>
        )}
      </div>
    </div>
  );
}

function ImportDetail({
  batchId,
  onClose,
  onDelete,
  onMessage,
}: {
  batchId: string;
  onClose: () => void;
  onDelete: () => void;
  onMessage: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["imports", batchId],
    queryFn: () => importsApi.get(batchId),
  });
  const batch = detail.data;
  const finished = batch ? ["completed", "partial", "cancelled", "failed"].includes(batch.status) : false;
  // Read existing rows instead of calling POST /preview, which rebuilds the
  // row set and would discard manual skip/edit decisions made earlier.
  const rows = useQuery({
    queryKey: ["imports", batchId, "rows"],
    queryFn: () => importsApi.rows(batchId, { page_size: 100 }),
    enabled: Boolean(batch),
  });

  const [mapping, setMapping] = useState<ImportMappingInput>({
    header_row: 1,
    amount_mode: "signed_positive_income",
    columns: {},
    fuzzy_dedupe: false,
  });
  const [onDuplicate, setOnDuplicate] = useState<"skip" | "allow">("skip");
  const [createStatus, setCreateStatus] = useState<"confirmed" | "draft">("confirmed");

  useEffect(() => {
    if (!batch?.mapping) return;
    const stored = batch.mapping as {
      header_row?: number;
      columns?: ImportMappingInput["columns"];
      amount_mode?: ImportMappingInput["amount_mode"];
      direction_map?: Record<string, string>;
      fuzzy_dedupe?: boolean;
    };
    setMapping({
      header_row: stored.header_row ?? 1,
      columns: stored.columns ?? {},
      amount_mode: stored.amount_mode ?? "signed_positive_income",
      direction_map: stored.direction_map ?? {},
      fuzzy_dedupe: stored.fuzzy_dedupe ?? false,
    });
  }, [batch?.id, batch?.mapping]);

  const saveMapping = useMutation({
    mutationFn: async () => {
      await importsApi.mapping(batchId, mapping);
      return importsApi.preview(batchId);
    },
    onSuccess: async () => {
      onMessage("字段映射已保存，已生成预览。");
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
      await queryClient.invalidateQueries({ queryKey: ["imports", batchId] });
    },
  });

  const skipInvalid = useMutation({
    mutationFn: () => importsApi.skipInvalid(batchId),
    onSuccess: async () => {
      onMessage("已跳过无效行");
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
      await queryClient.invalidateQueries({ queryKey: ["imports", batchId] });
    },
  });

  const confirm = useMutation({
    mutationFn: () => importsApi.confirm(batchId, { on_duplicate: onDuplicate, create_status: createStatus }),
    onSuccess: async (result) => {
      onMessage(`导入完成：成功 ${result.imported_rows} 行，无效 ${result.invalid_rows} 行。`);
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
      await queryClient.invalidateQueries({ queryKey: ["imports", batchId] });
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["statistics"] });
    },
  });

  const cancel = useMutation({
    mutationFn: () => importsApi.cancel(batchId),
    onSuccess: async () => {
      onMessage("导入已取消");
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
      await queryClient.invalidateQueries({ queryKey: ["imports", batchId] });
    },
  });

  const skipRow = useMutation({
    mutationFn: (rowId: string) =>
      importsApi.updateRow(batchId, rowId, { status: "skipped" }),
    onSuccess: async () => {
      onMessage("已跳过该行");
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
      await queryClient.invalidateQueries({ queryKey: ["imports", batchId] });
    },
  });

  if (detail.isLoading) {
    return (
      <Card>
        <Spinner />
      </Card>
    );
  }
  if (detail.isError || !batch) {
    return (
      <Card className="p-5">
        <ErrorBanner message={errorMessage(detail.error)} />
      </Card>
    );
  }

  const mutationError =
    saveMapping.error ?? skipInvalid.error ?? confirm.error ?? cancel.error ?? skipRow.error;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={batch.original_filename ?? "导入批次"}
          description={`${batch.source_format.toUpperCase()} · ${batch.total_rows} 行 · ${STATUS_LABELS[batch.status] ?? batch.status}`}
          action={
            <div className="flex gap-1">
              <Button variant="ghost" className="h-8 px-2 text-xs" onClick={onClose}>
                收起
              </Button>
              {!finished ? (
                <Button variant="ghost" className="h-8 px-2 text-xs" onClick={() => cancel.mutate()}>
                  取消导入
                </Button>
              ) : null}
              <Button
                variant="ghost"
                className="h-8 px-2 text-xs text-red-600"
                onClick={() => {
                  if (window.confirm("确认删除该导入批次及其文件记录？")) onDelete();
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          }
        />
        <div className="grid gap-3 p-5 sm:grid-cols-4">
          <Stat label="有效" value={batch.valid_rows} tone="text-primary-700" />
          <Stat label="无效" value={batch.invalid_rows} tone="text-red-600" />
          <Stat label="重复" value={batch.duplicate_rows} tone="text-amber-700" />
          <Stat label="已导入" value={batch.imported_rows} tone="text-blue-700" />
        </div>
        {batch.error_message ? (
          <div className="px-5 pb-5">
            <ErrorBanner message={`${batch.error_code ?? "IMPORT_ERROR"}: ${batch.error_message}`} />
          </div>
        ) : null}
      </Card>

      {!finished ? (
        <Card>
          <CardHeader title="字段映射" description="选择源文件列与标准字段的对应关系" />
          <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="标题行">
              <Input
                type="number"
                min={1}
                value={mapping.header_row}
                onChange={(event) =>
                  setMapping((value) => ({ ...value, header_row: Number(event.target.value) || 1 }))
                }
              />
            </Field>
            <Field label="金额模式">
              <Select
                value={mapping.amount_mode}
                onChange={(event) =>
                  setMapping((value) => ({
                    ...value,
                    amount_mode: event.target.value as ImportMappingInput["amount_mode"],
                  }))
                }
              >
                <option value="signed_positive_income">正数收入 / 负数支出</option>
                <option value="signed_positive_expense">正数支出 / 负数收入</option>
                <option value="type_column">方向列</option>
                <option value="debit_credit">借方 / 贷方两列</option>
              </Select>
            </Field>
            <Field label="模糊去重" hint="同账户、金额相等、±1 天且描述相近">
              <Select
                value={mapping.fuzzy_dedupe ? "yes" : "no"}
                onChange={(event) =>
                  setMapping((value) => ({
                    ...value,
                    fuzzy_dedupe: event.target.value === "yes",
                  }))
                }
              >
                <option value="no">关闭</option>
                <option value="yes">开启</option>
              </Select>
            </Field>
            {MAPPING_FIELDS.map((field) => (
              <Field key={field.key} label={field.label}>
                <Select
                  value={mapping.columns[field.key] ?? ""}
                  onChange={(event) =>
                    setMapping((value) => ({
                      ...value,
                      columns: { ...value.columns, [field.key]: event.target.value || null },
                    }))
                  }
                >
                  <option value="">未映射</option>
                  {batch.columns.map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </Select>
              </Field>
            ))}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink/8 px-5 py-4">
            <p className="text-xs text-ink/45">
              至少映射“交易日期”和金额列；银行账单可改用方向列或借贷两列。
            </p>
            <div className="flex gap-2">
              {batch.status === "previewed" ? (
                <Button
                  variant="outline"
                  onClick={async () => {
                    await queryClient.invalidateQueries({ queryKey: ["imports", batchId] });
                  }}
                >
                  刷新
                </Button>
              ) : null}
              <Button
                onClick={() => saveMapping.mutate()}
                disabled={
                  saveMapping.isPending ||
                  !mapping.columns.transaction_date ||
                  (!mapping.columns.amount && !mapping.columns.debit && !mapping.columns.credit)
                }
              >
                {saveMapping.isPending ? "处理中…" : "保存映射并预览"}
              </Button>
            </div>
          </div>
        </Card>
      ) : null}

      {mutationError ? <ErrorBanner message={errorMessage(mutationError)} /> : null}
      {rows.isError ? <ErrorBanner message={errorMessage(rows.error)} /> : null}

      {batch.status !== "uploaded" ? (
        rows.isLoading ? (
          <Card>
            <Spinner label="正在读取预览…" />
          </Card>
        ) : (
          <Card>
          <CardHeader
            title="预览与确认"
            description="确认后将写入正式收支记录"
            action={
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  className="h-8 px-2.5 text-xs"
                  onClick={() => skipInvalid.mutate()}
                  disabled={skipInvalid.isPending || !batch.invalid_rows}
                >
                  跳过无效行
                </Button>
                {batch.status === "previewed" ? (
                  <Button
                    className="h-8 px-3 text-xs"
                    onClick={() => confirm.mutate()}
                    disabled={confirm.isPending || !batch.valid_rows}
                  >
                    {confirm.isPending ? "导入中…" : `确认导入 ${batch.valid_rows} 行`}
                  </Button>
                ) : null}
              </div>
            }
          />
          <div className="flex flex-wrap gap-3 border-b border-ink/8 px-5 py-3 text-xs">
            <label className="flex items-center gap-2 text-ink/55">
              重复行
              <Select
                className="h-8 w-28 text-xs"
                value={onDuplicate}
                onChange={(event) => setOnDuplicate(event.target.value as "skip" | "allow")}
              >
                <option value="skip">跳过</option>
                <option value="allow">允许导入</option>
              </Select>
            </label>
            <label className="flex items-center gap-2 text-ink/55">
              写入状态
              <Select
                className="h-8 w-28 text-xs"
                value={createStatus}
                onChange={(event) =>
                  setCreateStatus(event.target.value as "confirmed" | "draft")
                }
              >
                <option value="confirmed">已确认</option>
                <option value="draft">草稿</option>
              </Select>
            </label>
          </div>
          {rows.data && rows.data.items.length ? (
            <div className="max-h-[420px] overflow-auto">
              <table className="w-full min-w-[640px] text-left text-xs">
                <thead className="sticky top-0 bg-white">
                  <tr className="border-b border-ink/8 uppercase tracking-wide text-ink/40">
                    <th className="px-4 py-2.5 font-medium">行</th>
                    <th className="px-3 py-2.5 font-medium">日期</th>
                    <th className="px-3 py-2.5 font-medium">金额</th>
                    <th className="px-3 py-2.5 font-medium">描述</th>
                    <th className="px-3 py-2.5 font-medium">状态</th>
                    <th className="px-4 py-2.5 text-right font-medium">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink/6">
                  {rows.data.items.map((row) => (
                    <tr key={row.id} className={row.status === "invalid" ? "bg-red-50/40" : ""}>
                      <td className="px-4 py-2.5 text-ink/40">{row.row_number}</td>
                      <td className="px-3 py-2.5 text-ink/70">{stringValue(row, "transaction_date")}</td>
                      <td className="px-3 py-2.5 text-ink/70">{stringValue(row, "amount")}</td>
                      <td className="max-w-52 truncate px-3 py-2.5 text-ink/55">
                        {stringValue(row, "description") || "—"}
                      </td>
                      <td className="px-3 py-2.5">
                        <RowStatus row={row} />
                        {row.errors.length ? (
                          <p className="mt-0.5 max-w-56 truncate text-[11px] text-red-500">
                            {row.errors[0]?.message}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {["invalid", "duplicate", "valid"].includes(row.status) &&
                        batch.status !== "completed" ? (
                          <Button
                            variant="ghost"
                            className="h-7 px-2 text-[11px]"
                            onClick={() => skipRow.mutate(row.id)}
                          >
                            跳过
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="没有预览行" description="检查字段映射后重新生成预览。" />
          )}
          </Card>
        )
      ) : null}

      {finished ? (
        <Card className="p-5">
          <p className="text-sm text-ink/70">
            <FileSpreadsheet className="mr-2 inline h-4 w-4 text-ink/40" />
            该批次已结束，共导入 {batch.imported_rows} 行
            {batch.completed_at ? ` · ${formatDate(batch.completed_at)}` : ""}。
          </p>
        </Card>
      ) : null}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-xl bg-canvas/60 px-3 py-2.5">
      <p className="text-xs text-ink/45">{label}</p>
      <p className={`mt-0.5 text-lg font-semibold ${tone}`}>{value}</p>
    </div>
  );
}

function RowStatus({ row }: { row: ImportRow }) {
  const map: Record<string, { label: string; tone: "green" | "red" | "amber" | "slate" | "blue" }> = {
    valid: { label: "有效", tone: "green" },
    invalid: { label: "无效", tone: "red" },
    duplicate: { label: "重复", tone: "amber" },
    skipped: { label: "已跳过", tone: "slate" },
    imported: { label: "已导入", tone: "blue" },
    pending: { label: "待处理", tone: "slate" },
  };
  const status = map[row.status] ?? { label: row.status, tone: "slate" as const };
  return <Badge tone={status.tone}>{status.label}</Badge>;
}

function stringValue(row: ImportRow, key: string): string {
  const value = row.normalized_data?.[key];
  if (value === null || value === undefined) return "";
  return String(value);
}

function statusTone(status: string): "green" | "red" | "amber" | "slate" | "blue" {
  switch (status) {
    case "completed":
      return "green";
    case "partial":
      return "amber";
    case "failed":
      return "red";
    case "previewed":
      return "blue";
    case "cancelled":
      return "slate";
    default:
      return "slate";
  }
}
