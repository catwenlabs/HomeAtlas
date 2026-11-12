import { useQuery } from "@tanstack/react-query";

import { accountsApi, categoriesApi, currenciesApi } from "../api/endpoints";

export function useAccounts(includeInactive = false) {
  return useQuery({
    queryKey: ["accounts", includeInactive],
    queryFn: () =>
      accountsApi.list({ page_size: 100, ...(includeInactive ? {} : { is_active: true }) }),
    select: (page) => page.items,
  });
}

export function useCategories() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
    select: (page) => page.items,
  });
}

export function useCurrencies() {
  return useQuery({
    queryKey: ["currencies"],
    queryFn: currenciesApi.list,
    select: (page) => page.items,
  });
}

export function useAccountNames() {
  const query = useAccounts(true);
  const map = new Map((query.data ?? []).map((account) => [account.id, account.name]));
  return { ...query, names: map };
}

export function useCategoryNames() {
  const query = useCategories();
  const map = new Map((query.data ?? []).map((category) => [category.id, category.name]));
  return { ...query, names: map };
}
