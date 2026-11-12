import { api, unwrap } from "./client";
import type {
  Account,
  AccountBalances,
  Category,
  CategoryStatistics,
  Currency,
  Envelope,
  Household,
  ImportBatch,
  ImportPreview,
  ImportRow,
  MonthlyStatistics,
  OverviewStatistics,
  Page,
  Session,
  SetupOptions,
  SetupPayload,
  SetupStatus,
  Transaction,
  Transfer,
  User,
} from "./types";

type Params = object;

const get = <T>(url: string, params?: Params) =>
  unwrap<T>(api.get<Envelope<T>>(url, { params }));

const post = <T>(url: string, data?: unknown) =>
  unwrap<T>(api.post<Envelope<T>>(url, data));

const put = <T>(url: string, data?: unknown) =>
  unwrap<T>(api.put<Envelope<T>>(url, data));

const remove = <T = null>(url: string) => unwrap<T>(api.delete<Envelope<T>>(url));

export interface TransactionQuery {
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  start_date?: string;
  end_date?: string;
  account_id?: string;
  category_id?: string;
  transaction_type?: "income" | "expense" | "opening_balance";
  currency?: string;
  min_amount?: string;
  max_amount?: string;
  keyword?: string;
  status?: "draft" | "confirmed" | "reversed";
}

export interface TransferQuery {
  page?: number;
  page_size?: number;
  start_date?: string;
  end_date?: string;
  account_id?: string;
  status?: "draft" | "confirmed" | "reversed";
}

export interface TransactionInput {
  account_id: string;
  category_id?: string | null;
  transaction_type: "income" | "expense";
  amount: string;
  currency?: string;
  exchange_rate?: string;
  transaction_date?: string;
  description?: string | null;
  status?: "draft" | "confirmed";
  /** Optimistic lock: reject with 409 TRANSACTION_CONFLICT when stale. */
  expected_updated_at?: string;
}

export interface TransferInput {
  from_account_id: string;
  to_account_id: string;
  from_amount: string;
  from_currency?: string;
  to_amount: string;
  to_currency?: string;
  exchange_rate?: string;
  fee?: string;
  transfer_date?: string;
  description?: string | null;
  status?: "draft" | "confirmed";
}

export interface ColumnMappingInput {
  transaction_date?: string | null;
  amount?: string | null;
  direction?: string | null;
  debit?: string | null;
  credit?: string | null;
  description?: string | null;
  category?: string | null;
  currency?: string | null;
  external_id?: string | null;
  exchange_rate?: string | null;
  account?: string | null;
}

export interface ImportMappingInput {
  header_row: number;
  columns: ColumnMappingInput;
  amount_mode:
    | "signed_positive_income"
    | "signed_positive_expense"
    | "type_column"
    | "debit_credit";
  direction_map?: Record<string, string>;
  default_category_id?: string | null;
  fuzzy_dedupe?: boolean;
  fuzzy_threshold?: number;
  fuzzy_date_window_days?: number;
}

export const setupApi = {
  status: () => get<SetupStatus>("/setup/status"),
  options: () => get<SetupOptions>("/setup/options"),
  complete: (payload: SetupPayload) => post<Session>("/setup", payload),
};

export const authApi = {
  login: (username: string, password: string) =>
    post<Session>("/auth/login", { username, password }),
  me: () => get<{ user: User; household: Household | null }>("/auth/me"),
  logout: () => post<null>("/auth/logout"),
};

export const usersApi = {
  list: () => get<User[]>("/users"),
  create: (payload: {
    username: string;
    password: string;
    display_name: string;
    role: "owner" | "member";
  }) => post<User>("/users", payload),
  update: (
    id: string,
    payload: {
      display_name?: string;
      password?: string;
      role?: "owner" | "member";
      is_active?: boolean;
    },
  ) => put<User>(`/users/${id}`, payload),
};

export const householdsApi = {
  update: (
    id: string,
    payload: { name?: string; base_currency?: string; timezone?: string },
  ) => put<Household>(`/households/${id}`, payload),
};

export const accountsApi = {
  list: (params?: { page?: number; page_size?: number; is_active?: boolean }) =>
    get<Page<Account>>("/accounts", params),
  create: (payload: {
    name: string;
    institution?: string | null;
    account_type?: string;
    currency?: string;
  }) => post<Account>("/accounts", payload),
  update: (
    id: string,
    payload: {
      name?: string;
      institution?: string | null;
      account_type?: string;
      currency?: string;
      is_active?: boolean;
    },
  ) => put<Account>(`/accounts/${id}`, payload),
  remove: (id: string) => remove(`/accounts/${id}`),
  balances: (id: string) => get<AccountBalances>(`/accounts/${id}/balances`),
  setOpeningBalance: (
    id: string,
    payload: { amount: string; currency?: string; transaction_date?: string; description?: string },
  ) => put<Transaction>(`/accounts/${id}/opening-balance`, payload),
};

export const categoriesApi = {
  list: (params?: { category_type?: "income" | "expense"; is_active?: boolean }) =>
    get<Page<Category>>("/categories", { page_size: 100, ...params }),
  create: (payload: {
    name: string;
    category_type: "income" | "expense";
    parent_id?: string | null;
    icon?: string | null;
    sort_order?: number;
  }) => post<Category>("/categories", payload),
  update: (
    id: string,
    payload: {
      name?: string;
      category_type?: "income" | "expense";
      parent_id?: string | null;
      icon?: string | null;
      sort_order?: number;
      is_active?: boolean;
    },
  ) => put<Category>(`/categories/${id}`, payload),
  remove: (id: string) => remove(`/categories/${id}`),
};

export const currenciesApi = {
  list: () => get<Page<Currency>>("/currencies", { page_size: 100, is_active: true }),
};

export const transactionsApi = {
  list: (params: TransactionQuery = {}) =>
    get<Page<Transaction>>("/transactions", { ...params }),
  create: (payload: TransactionInput) => post<Transaction>("/transactions", payload),
  update: (id: string, payload: Partial<TransactionInput>) =>
    put<Transaction>(`/transactions/${id}`, payload),
  remove: (id: string) => remove(`/transactions/${id}`),
  reverse: (id: string, payload?: { description?: string }) =>
    post<Transaction>(`/transactions/${id}/reverse`, payload ?? {}),
};

export const transfersApi = {
  list: (params: TransferQuery = {}) =>
    get<Page<Transfer>>("/transfers", { ...params }),
  create: (payload: TransferInput) => post<Transfer>("/transfers", payload),
  update: (id: string, payload: Partial<TransferInput>) =>
    put<Transfer>(`/transfers/${id}`, payload),
  remove: (id: string) => remove(`/transfers/${id}`),
  reverse: (id: string) => post<Transfer>(`/transfers/${id}/reverse`, {}),
};

export const statisticsApi = {
  overview: (params?: { start_date?: string; end_date?: string }) =>
    get<OverviewStatistics>("/statistics/overview", params),
  incomeExpense: (params?: { start_date?: string; end_date?: string }) =>
    get<OverviewStatistics>("/statistics/income-expense", params),
  accountBalances: () =>
    get<{
      base_currency: string;
      balances: (CurrencyBalance & { account_count: number })[];
      accounts: {
        account_id: string;
        name: string;
        account_type: string;
        is_active: boolean;
        balances: CurrencyBalance[];
      }[];
    }>("/statistics/account-balances"),
  category: (params?: {
    start_date?: string;
    end_date?: string;
    transaction_type?: "income" | "expense";
  }) => get<CategoryStatistics>("/statistics/category", params),
  monthly: (params?: { start_date?: string; end_date?: string }) =>
    get<MonthlyStatistics>("/statistics/monthly", params),
};

type CurrencyBalance = { currency: string; book_balance: string };

export const importsApi = {
  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    get<Page<ImportBatch>>("/imports", params),
  get: (id: string) => get<ImportBatch>(`/imports/${id}`),
  upload: (file: File, accountId?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (accountId) form.append("account_id", accountId);
    return unwrap<ImportBatch>(
      api.post<Envelope<ImportBatch>>("/imports", form, {
        headers: { "Content-Type": "multipart/form-data" },
      }),
    );
  },
  mapping: (id: string, payload: ImportMappingInput) =>
    put<ImportBatch>(`/imports/${id}/mapping`, payload),
  preview: (id: string) => post<ImportPreview>(`/imports/${id}/preview`),
  rows: (id: string, params?: { page?: number; page_size?: number; status?: string }) =>
    get<Page<ImportRow>>(`/imports/${id}/rows`, params),
  updateRow: (
    batchId: string,
    rowId: string,
    payload: {
      normalized_data?: Record<string, unknown>;
      status?: "pending" | "valid" | "skipped";
    },
  ) => put<ImportRow>(`/imports/${batchId}/rows/${rowId}`, payload),
  skipInvalid: (id: string) =>
    post<{ batch: ImportBatch; skipped_rows: number }>(`/imports/${id}/rows/skip`, {
      scope: "invalid",
    }),
  confirm: (
    id: string,
    payload: { on_duplicate?: "skip" | "allow"; create_status?: "confirmed" | "draft" },
  ) => post<ImportBatch>(`/imports/${id}/confirm`, payload),
  cancel: (id: string) => post<ImportBatch>(`/imports/${id}/cancel`),
  remove: (id: string) => remove(`/imports/${id}`),
  downloadTemplate: async (format: "csv" | "xlsx") => {
    const response = await api.get<Blob>("/imports/template", {
      params: { format },
      responseType: "blob",
    });
    return response.data;
  },
};
