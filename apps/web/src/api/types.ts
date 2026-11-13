export interface Envelope<T> {
  success: boolean;
  data: T;
  message: string | null;
  error_code?: string;
}

export interface User {
  id: string;
  household_id: string;
  username: string;
  display_name: string;
  role: "owner" | "member";
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Household {
  id: string;
  name: string;
  base_currency: string;
  timezone: string;
}

export interface Session {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
  household: Household;
}

export interface SetupStatus {
  initialized: boolean;
  household_name: string | null;
}

export interface SetupCurrencyOption {
  code: string;
  name: string;
  symbol: string;
  decimal_places: number;
}

export interface SetupCategoryOption {
  name: string;
  category_type: "income" | "expense";
  sort_order: number;
  icon: string | null;
}

export interface SetupOptions {
  currencies: SetupCurrencyOption[];
  categories: SetupCategoryOption[];
  timezones: { value: string; label: string }[];
}

export interface SetupCategoryPayload {
  name: string;
  category_type: "income" | "expense";
  sort_order: number;
  icon?: string | null;
}

export interface SetupPayload {
  username: string;
  password: string;
  display_name?: string;
  household_name: string;
  base_currency: string;
  timezone: string;
  currency_codes: string[];
  categories: SetupCategoryPayload[];
}

export interface Account {
  id: string;
  household_id: string;
  name: string;
  institution: string | null;
  account_type: "bank" | "cash" | "wallet" | "other" | "credit" | "investment";
  currency: string;
  external_ref: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Category {
  id: string;
  household_id: string;
  name: string;
  category_type: "income" | "expense";
  parent_id: string | null;
  icon: string | null;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Transaction {
  id: string;
  household_id: string;
  account_id: string;
  category_id: string | null;
  transaction_type: "income" | "expense" | "opening_balance";
  amount: string;
  currency: string;
  base_amount: string;
  base_currency: string;
  exchange_rate: string;
  exchange_rate_date: string;
  transaction_date: string;
  description: string | null;
  source: string;
  external_id: string | null;
  status: "draft" | "confirmed" | "reversed";
  reverses_transaction_id: string | null;
  transfer_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Transfer {
  id: string;
  household_id: string;
  from_account_id: string;
  to_account_id: string;
  from_amount: string;
  from_currency: string;
  to_amount: string;
  to_currency: string;
  exchange_rate: string;
  base_amount: string | null;
  base_currency: string | null;
  fee: string;
  fee_currency: string;
  transfer_date: string;
  description: string | null;
  status: "draft" | "confirmed" | "reversed";
  reverses_transfer_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Currency {
  code: string;
  name: string;
  symbol: string;
  decimal_places: number;
  is_active: boolean;
}

export interface BalanceLine {
  currency: string;
  book_balance: string;
  latest_snapshot: {
    id: string;
    currency: string;
    balance: string;
    snapshot_at: string;
    source: string;
    created_at: string;
  } | null;
  difference: string | null;
}

export interface AccountBalances {
  account_id: string;
  balances: BalanceLine[];
}

export interface CurrencyBalance {
  currency: string;
  book_balance: string;
}

export interface CurrencyBalanceTotal extends CurrencyBalance {
  account_count: number;
}

export interface OverviewStatistics {
  start_date: string;
  end_date: string;
  base_currency: string;
  income: string;
  expense: string;
  net: string;
  income_count: number;
  expense_count: number;
  transaction_count: number;
  assets: CurrencyBalance[];
  account_count: number;
}

export interface CategoryStatItem {
  category_id: string | null;
  category_name: string;
  category_type: string;
  amount: string;
  percentage: string;
  transaction_count: number;
}

export interface CategoryStatistics {
  start_date: string;
  end_date: string;
  base_currency: string;
  income_total: string;
  expense_total: string;
  items: CategoryStatItem[];
}

export interface PeriodStatisticsItem {
  period: string;
  income: string;
  expense: string;
  net: string;
  income_count: number;
  expense_count: number;
  transaction_count: number;
}

export interface MonthlyStatistics {
  start_date: string;
  end_date: string;
  base_currency: string;
  granularity: "month" | "year";
  income_total: string;
  expense_total: string;
  net_total: string;
  items: PeriodStatisticsItem[];
}

export interface ImportRowError {
  code: string;
  field: string | null;
  message: string;
}

export interface ImportRow {
  id: string;
  batch_id: string;
  row_number: number;
  raw_data: string[];
  normalized_data: Record<string, unknown> | null;
  row_hash: string | null;
  status: "pending" | "valid" | "invalid" | "duplicate" | "skipped" | "imported";
  errors: ImportRowError[];
  transaction_id: string | null;
  duplicate_of_transaction_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ImportBatch {
  id: string;
  household_id: string;
  account_id: string | null;
  status: string;
  source_format: string;
  original_filename: string | null;
  file_sha256: string;
  file_size_bytes: number;
  columns: string[];
  sample_rows: string[][];
  mapping: Record<string, unknown> | null;
  mapping_version: number;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  imported_rows: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
  completed_at: string | null;
}

export interface ImportPreview extends ImportBatch {
  preview: ImportRow[];
}

// ---------- Phase 2C: assets, investments, loans, market ----------

export interface AssetBuckets {
  idle: string;
  invested: string;
  matured: string;
}

export interface CurrencyAssetLine {
  currency: string;
  cash: string;
  invested: string;
  liabilities: string;
  fx_rate: string;
}

export interface MaturedInvestment {
  id: string;
  name: string;
  end_date: string;
  current_value: string;
  currency: string;
}

export interface AssetsSummary {
  base_currency: string;
  net_worth: string;
  buckets: AssetBuckets;
  total_liabilities: string;
  unrealized_pnl: string;
  unmapped_cash: string;
  daily_interest_income: string;
  daily_interest_expense: string;
  inactive_count: number;
  matured_investments: MaturedInvestment[];
  currency_breakdown: CurrencyAssetLine[];
  fx_rates_used: Record<string, string>;
}

export interface NetWorthSnapshot {
  id: string;
  household_id: string;
  snapshot_date: string;
  base_currency: string;
  total_cash: string;
  total_invested: string;
  total_liabilities: string;
  net_worth: string;
  unrealized_pnl: string;
  unmapped_cash: string;
  daily_interest_income: string;
  daily_interest_expense: string;
  currency_breakdown: CurrencyAssetLine[];
  fx_rates_used: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export interface Investment {
  id: string;
  household_id: string;
  name: string;
  investment_type: "fixed" | "daily" | "fund" | "cash" | "stock" | "bond" | "other";
  account_id: string | null;
  principal: string;
  current_value: string;
  currency: string;
  annual_rate: string | null;
  start_date: string;
  end_date: string | null;
  liquidity: string | null;
  status: "active" | "redeemed";
  realized_pnl: string | null;
  pre_redeem_value: string | null;
  remark: string | null;
  created_at: string;
  updated_at: string;
  matured: boolean;
  tag_ids: string[];
  holdings_cost?: string | null;
}

export interface InvestmentTag {
  id: string;
  household_id: string;
  name: string;
  color: string | null;
  created_at: string;
  updated_at: string;
}

export interface Holding {
  id: string;
  investment_id: string;
  market: "SH" | "SZ" | "HK" | "US";
  symbol: string;
  quantity: string;
  cost_price: string;
  cost_subtotal: string | null;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

export interface HoldingsSummary {
  items: Holding[];
  holdings_cost: string;
}

export interface RefreshValueResult {
  current_value: string;
  previous_value: string;
  items: {
    market: string;
    symbol: string;
    name: string;
    quantity: string;
    price: string;
    currency: string;
    subtotal: string;
  }[];
}

export interface Quote {
  market: string;
  symbol: string;
  name: string;
  price: string;
  currency: string;
  quoted_at: string;
}

export interface Loan {
  id: string;
  household_id: string;
  name: string;
  institution: string | null;
  principal: string;
  currency: string;
  annual_rate: string;
  start_date: string;
  end_date: string | null;
  due_day: number | null;
  repayment_type: "monthly_interest" | "one_time";
  linked_account_id: string | null;
  remaining_principal: string;
  status: "active" | "settled";
  settled_date: string | null;
  remark: string | null;
  created_at: string;
  updated_at: string;
  daily_interest: string | null;
}

export interface ExchangeRate {
  id: string;
  household_id: string;
  base_currency: string;
  quote_currency: string;
  rate: string;
  rate_date: string;
  source: string;
  created_at: string;
  updated_at: string;
}
