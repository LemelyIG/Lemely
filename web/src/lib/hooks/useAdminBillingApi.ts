import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type UseInfiniteQueryResult,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import { PartialSaveError, adminRetry } from "@/lib/adminBillingModel"
import { toAdminCatalogue } from "@/lib/billingAdapters"
import type {
  AdminAdjustRequest,
  AdminCancelRequest,
  AdminCatalogue,
  AdminCreditPack,
  AdminExtendRequest,
  AdminForgiveRequest,
  AdminGrantRequest,
  AdminPaymentRow,
  AdminPaymentsPage,
  AdminRefundRequest,
  BillingHealth,
  CustomerDetail,
  CustomerSearchResult,
  EstimatorCreate,
  EstimatorRow,
  FreeAllowanceUpdate,
  ManualActivationRequest,
  MarginReport,
  PackCreate,
  PackUpdate,
  PaymentStatus,
  ProblemQueue,
  RateCreate,
  Reasoned,
  TierCreate,
  TierUpdate,
  UsageRateRow,
  WireAdminCatalogue,
  WireAdminPlanTier,
  WireFreeAllowance,
} from "@/lib/billingTypes"

/*
 * React-query hooks over `/api/admin/billing/*` (plan 07), all `platform_admin` only. Same
 * rule as `useAdminApi.ts`: no `fallback` anywhere, because an empty payload on the console
 * whose job is noticing money trouble reads as "nothing is wrong". Paths omit `/api`.
 */

const enc = encodeURIComponent
const post = (b: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(b) })
const put = (b: unknown): RequestInit => ({ method: "PUT", body: JSON.stringify(b) })
const B = "/admin/billing"

export const adminBillingApi = {
  catalogue: () => request<WireAdminCatalogue>(`${B}/catalogue`),
  createTier: (b: TierCreate) => request<WireAdminPlanTier>(`${B}/tiers`, post(b)),
  updateTier: (id: string, b: TierUpdate) => request<WireAdminPlanTier>(`${B}/tiers/${enc(id)}`, put(b)),
  syncTier: (id: string, b: Reasoned) => request<WireAdminPlanTier>(`${B}/tiers/${enc(id)}/sync`, post(b)),
  createPack: (b: PackCreate) => request<AdminCreditPack>(`${B}/packs`, post(b)),
  updatePack: (id: string, b: PackUpdate) => request<AdminCreditPack>(`${B}/packs/${enc(id)}`, put(b)),
  createRate: (b: RateCreate) => request<UsageRateRow>(`${B}/rates`, post(b)),
  createEstimator: (b: EstimatorCreate) => request<EstimatorRow>(`${B}/estimators`, post(b)),
  updateFreeAllowance: (b: FreeAllowanceUpdate) => request<WireFreeAllowance>(`${B}/free-allowances`, put(b)),
  searchCustomers: (q: string) => request<CustomerSearchResult>(`${B}/customers?q=${enc(q)}`),
  customer: (userId: string) => request<CustomerDetail>(`${B}/customers/${enc(userId)}`),
  grant: (userId: string, b: AdminGrantRequest) => request<CustomerDetail>(`${B}/customers/${enc(userId)}/grant`, post(b)),
  adjust: (userId: string, b: AdminAdjustRequest) => request<CustomerDetail>(`${B}/customers/${enc(userId)}/adjust`, post(b)),
  forgiveDebt: (userId: string, b: AdminForgiveRequest) =>
    request<CustomerDetail>(`${B}/customers/${enc(userId)}/forgive-debt`, post(b)),
  manualActivation: (userId: string, b: ManualActivationRequest) =>
    request<CustomerDetail>(`${B}/customers/${enc(userId)}/manual-activation`, post(b)),
  extend: (subId: string, b: AdminExtendRequest) => request<CustomerDetail>(`${B}/subscriptions/${enc(subId)}/extend`, post(b)),
  cancelSubscription: (subId: string, b: AdminCancelRequest) =>
    request<CustomerDetail>(`${B}/subscriptions/${enc(subId)}/cancel`, post(b)),
  refund: (paymentId: string, b: AdminRefundRequest) => request<AdminPaymentRow>(`${B}/payments/${enc(paymentId)}/refund`, post(b)),
  voidPayment: (paymentId: string, b: Reasoned) => request<AdminPaymentRow>(`${B}/payments/${enc(paymentId)}/void`, post(b)),
  reconcile: (paymentId: string, b: Reasoned) => request<AdminPaymentRow>(`${B}/payments/${enc(paymentId)}/reconcile`, post(b)),
  payments: (status: PaymentStatus | null, cursor: string | null) => {
    const p = new URLSearchParams()
    if (status) p.set("status", status)
    if (cursor) p.set("cursor", cursor)
    const qs = p.toString()
    return request<AdminPaymentsPage>(qs ? `${B}/payments?${qs}` : `${B}/payments`)
  },
  problems: () => request<ProblemQueue>(`${B}/problems`),
  /** `from`/`to` are calendar days; the route takes ISO datetimes (whole days, UTC). */
  margin: (from: string, to: string) =>
    request<MarginReport>(`${B}/margin?from=${enc(`${from}T00:00:00Z`)}&to=${enc(`${to}T23:59:59Z`)}`),
  health: () => request<BillingHealth>(`${B}/health`),
}

export const adminBillingKeys = {
  all: ["admin", "billing"] as const,
  catalogue: ["admin", "billing", "catalogue"] as const,
  customers: (q: string) => ["admin", "billing", "customers", q] as const,
  customer: (userId: string) => ["admin", "billing", "customer", userId] as const,
  payments: (status: PaymentStatus | null) => ["admin", "billing", "payments", status ?? "all"] as const,
  problems: ["admin", "billing", "problems"] as const,
  margin: (from: string, to: string) => ["admin", "billing", "margin", from, to] as const,
  health: ["admin", "billing", "health"] as const,
}

export const useAdminCatalogue = (): UseQueryResult<AdminCatalogue, Error> =>
  useQuery({ queryKey: adminBillingKeys.catalogue, retry: adminRetry, queryFn: adminBillingApi.catalogue, select: toAdminCatalogue })

/** Catalogue writes return the single row, so the catalogue is refetched. */
function useCatalogueWrite<V, D>(fn: (v: V) => Promise<D>): UseMutationResult<D, Error, V> {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: adminBillingKeys.catalogue }) })
}

export const useCreateTier = () => useCatalogueWrite((b: TierCreate) => adminBillingApi.createTier(b))
export const useUpdateTier = () => useCatalogueWrite((v: { id: string; body: TierUpdate }) => adminBillingApi.updateTier(v.id, v.body))
export const useSyncTier = () => useCatalogueWrite((v: { id: string; body: Reasoned }) => adminBillingApi.syncTier(v.id, v.body))
export const useCreatePack = () => useCatalogueWrite((b: PackCreate) => adminBillingApi.createPack(b))
export const useUpdatePack = () => useCatalogueWrite((v: { id: string; body: PackUpdate }) => adminBillingApi.updatePack(v.id, v.body))
export const useCreateRate = () => useCatalogueWrite((b: RateCreate) => adminBillingApi.createRate(b))
export const useCreateEstimator = () => useCatalogueWrite((b: EstimatorCreate) => adminBillingApi.createEstimator(b))
const FREE_LABEL = { student: "the student free allowance", teacher: "the teacher signup credits" } as const

/**
 * One form, up to two requests (07 updates one audience per call), sent one after the other and
 * only for the audiences that changed. If the second fails after the first saved, a
 * `PartialSaveError` says which landed; the catalogue is refetched on settle either way so a
 * half-saved pair is visible, and a retry (computed against that refetch) sends only the rest.
 */
export const useUpdateFreeAllowances = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (updates: FreeAllowanceUpdate[]) => {
      const saved: WireFreeAllowance[] = []
      for (const update of updates) {
        try {
          saved.push(await adminBillingApi.updateFreeAllowance(update))
        } catch (error) {
          if (saved.length === 0) throw error
          throw new PartialSaveError(
            saved.map((s) => FREE_LABEL[s.audience]),
            FREE_LABEL[update.audience],
            error,
          )
        }
      }
      return saved
    },
    onSettled: () => qc.invalidateQueries({ queryKey: adminBillingKeys.catalogue }),
  })
}

export function useCustomerSearch(q: string): UseQueryResult<CustomerSearchResult, Error> {
  const term = q.trim()
  return useQuery({ queryKey: adminBillingKeys.customers(term), queryFn: () => adminBillingApi.searchCustomers(term), enabled: term.length >= 2, retry: adminRetry })
}

export const useCustomer = (userId: string): UseQueryResult<CustomerDetail, Error> =>
  useQuery({ queryKey: adminBillingKeys.customer(userId), queryFn: () => adminBillingApi.customer(userId), enabled: userId !== "", retry: adminRetry })

function useCustomerWrite<V extends { id: string }>(userId: string, fn: (v: V) => Promise<CustomerDetail>): UseMutationResult<CustomerDetail, Error, V> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => qc.setQueryData(adminBillingKeys.customer(userId), data),
    // A failed write may or may not have landed: refetch so the screen shows what is true. Not
    // returned, so the failure shows at once instead of waiting for the refetch to finish.
    onError: () => {
      void qc.invalidateQueries({ queryKey: adminBillingKeys.customer(userId) })
    },
  })
}

export const useGrantCredits = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: AdminGrantRequest }) => adminBillingApi.grant(v.id, v.body))
export const useAdjustBalance = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: AdminAdjustRequest }) => adminBillingApi.adjust(v.id, v.body))
export const useForgiveDebt = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: AdminForgiveRequest }) => adminBillingApi.forgiveDebt(v.id, v.body))
export const useManualActivation = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: ManualActivationRequest }) => adminBillingApi.manualActivation(v.id, v.body))
export const useExtendSubscription = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: AdminExtendRequest }) => adminBillingApi.extend(v.id, v.body))
export const useAdminCancelSubscription = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: AdminCancelRequest }) => adminBillingApi.cancelSubscription(v.id, v.body))

function usePaymentWrite<B>(fn: (id: string, b: B) => Promise<AdminPaymentRow>): UseMutationResult<AdminPaymentRow, Error, { id: string; body: B }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; body: B }) => fn(v.id, v.body),
    // On any outcome: a refusal (409 `refund_in_flight`, `not_voidable`) means the row on screen
    // is stale, and a dropped request may still have written a refund row.
    onSettled: () => qc.invalidateQueries({ queryKey: adminBillingKeys.all }),
  })
}

export const useRefundPayment = () => usePaymentWrite(adminBillingApi.refund)
export const useVoidPayment = () => usePaymentWrite(adminBillingApi.voidPayment)
export const useReconcilePayment = () => usePaymentWrite(adminBillingApi.reconcile)

export function useAdminPayments(status: PaymentStatus | null): UseInfiniteQueryResult<InfiniteData<AdminPaymentsPage, string | null>, Error> {
  return useInfiniteQuery({
    queryKey: adminBillingKeys.payments(status),
    queryFn: ({ pageParam }) => adminBillingApi.payments(status, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    retry: adminRetry,
  })
}

export const useProblemQueue = (): UseQueryResult<ProblemQueue, Error> =>
  useQuery({ queryKey: adminBillingKeys.problems, queryFn: adminBillingApi.problems, refetchInterval: 60_000, retry: adminRetry })

export const useMarginReport = (from: string, to: string): UseQueryResult<MarginReport, Error> =>
  useQuery({ queryKey: adminBillingKeys.margin(from, to), queryFn: () => adminBillingApi.margin(from, to), retry: adminRetry })

export const useBillingHealth = (): UseQueryResult<BillingHealth, Error> =>
  useQuery({ queryKey: adminBillingKeys.health, queryFn: adminBillingApi.health, refetchInterval: 60_000, retry: adminRetry })
