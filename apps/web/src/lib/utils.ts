export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function amount(value: string | number | null | undefined): string {
  const number = Number(value ?? 0);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function money(value: string | number | null | undefined, currency = "CNY"): string {
  const formatted = amount(value);
  return formatted === "—" ? `— ${currency}` : `${formatted} ${currency}`;
}

export function signedAmount(value: string | number | null | undefined): string {
  const number = Number(value ?? 0);
  if (!Number.isFinite(number)) return "—";
  return `${number > 0 ? "+" : ""}${amount(number)}`;
}

export function signedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

/** Plain decimal (no thousands separators) for editable amount inputs. */
export function decimalInput(value: string | number | null | undefined): string {
  const number = Number(value ?? 0);
  return Number.isFinite(number) ? number.toFixed(2) : "";
}

export function pnlPercent(
  current: string | number,
  basis: string | number,
): number | null {
  const currentValue = Number(current);
  const basisValue = Number(basis);
  if (!Number.isFinite(currentValue) || !Number.isFinite(basisValue) || basisValue === 0) {
    return null;
  }
  return ((currentValue - basisValue) / basisValue) * 100;
}

/** Chinese market convention: red = gain, green = loss. */
export function pnlClass(value: number): string {
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-500";
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function todayInput(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
}

export function currentMonthRange(): { start: string; end: string } {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const iso = (date: Date) =>
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
      date.getDate(),
    ).padStart(2, "0")}`;
  return { start: iso(start), end: iso(end) };
}

export function currentYearRange(): { start: string; end: string } {
  const year = new Date().getFullYear();
  return { start: `${year}-01-01`, end: `${year}-12-31` };
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "操作失败，请稍后重试";
}
