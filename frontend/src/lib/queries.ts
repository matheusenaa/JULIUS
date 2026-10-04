import { QueryClient, useQuery } from "@tanstack/react-query";

import { api, ApiError, qs } from "./api";
import type {
  Account,
  AuditEntry,
  BudgetStatus,
  Category,
  Dashboard,
  GoalStatus,
  Recurrence,
  Report,
  TransactionPage,
  UpcomingItem,
  User,
} from "./types";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 1000 * 60 * 60 * 24 * 7, // mantém cache para uso offline
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      refetchOnWindowFocus: true,
    },
  },
});

/** Após qualquer alteração financeira, tudo que depende de saldo é recarregado. */
export function invalidateFinance() {
  for (const key of ["dashboard", "transactions", "accounts", "reports", "budgets", "goals", "recurrences", "occurrences", "audit"]) {
    queryClient.invalidateQueries({ queryKey: [key] });
  }
}

export const useMe = () =>
  useQuery({
    queryKey: ["me"],
    queryFn: () => api<User | null>("/api/auth/session"),
    staleTime: 5 * 60_000,
  });

export const useAccounts = () => useQuery({ queryKey: ["accounts"], queryFn: () => api<Account[]>("/api/accounts") });
export const useCategories = () =>
  useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/api/categories"), staleTime: 5 * 60_000 });
export const useDashboard = () => useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/api/dashboard") });
export const useRecurrences = () =>
  useQuery({ queryKey: ["recurrences"], queryFn: () => api<Recurrence[]>("/api/recurrences") });
export const useOccurrences = (days = 31) =>
  useQuery({
    queryKey: ["occurrences", days],
    queryFn: () => api<(UpcomingItem & { recurrence_id: string; account_id: string })[]>(`/api/recurrences/occurrences${qs({ days })}`),
  });
export const useBudgets = () => useQuery({ queryKey: ["budgets"], queryFn: () => api<BudgetStatus[]>("/api/budgets") });
export const useGoals = () => useQuery({ queryKey: ["goals"], queryFn: () => api<GoalStatus[]>("/api/goals") });
export const useAudit = () => useQuery({ queryKey: ["audit"], queryFn: () => api<AuditEntry[]>("/api/audit?limit=100") });
export const useAiStatus = () =>
  useQuery({
    queryKey: ["ai-status"],
    queryFn: () => api<{ enabled: boolean; provider: string | null }>("/api/ai/status"),
    staleTime: 10 * 60_000,
  });

export interface TxFilters {
  start?: string;
  end?: string;
  type?: string;
  account_id?: string;
  category_id?: string;
  payment_method?: string;
  status?: string;
  q?: string;
  min_cents?: number;
  max_cents?: number;
  recurring?: boolean;
  uncategorized?: boolean;
  page?: number;
}

export const useTransactions = (f: TxFilters) =>
  useQuery({
    queryKey: ["transactions", f],
    queryFn: () => api<TransactionPage>(`/api/transactions${qs({ ...f, page_size: 50 } as Record<string, string | number | boolean | undefined>)}`),
    placeholderData: (prev) => prev,
  });

export const useReport = (period: string, ref: string) =>
  useQuery({
    queryKey: ["reports", period, ref],
    queryFn: () => api<Report>(`/api/reports${qs({ period, ref })}`),
    placeholderData: (prev) => prev,
  });
