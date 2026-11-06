import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient, type QueryClient, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import { usageKeys } from "@/lib/hooks/useUsageApi"
import { toAutoTopup, toBillingSummary, toCatalogue, toSavedCard } from "@/lib/billingAdapters"
import type {
  Audience,
  AutoTopupSettings,
  AutoTopupUpdate,
  BillingSummary,
  Catalogue,
  CheckoutResponse,
  MerchantChargeStarted,
  PackCheckoutRequest,
  PaymentStatus,
  PaymentStatusView,
  Quote,
  Receipt,
  SavedCardView,
  SeatReductionResult,
  SubscriptionCheckoutRequest,
  WireAutoTopup,
  WireBillingSummary,
  WireCatalogue,
  WireCharge,
  WireCheckout,
  WirePaymentStatus,
  WireQuote,
  WireReceiptList,
  WireSavedCardList,
  WireSeats,
  WireSubscription,
  WireSubscriptionCheckout,
} from "@/lib/billingTypes"

/*
 * React-query hooks over `/api/billing/*` (plans 02, 05, 06). Paths omit `/api`: `request()`
 * adds it. Fetchers return wire DTOs; hooks adapt them to view types. No `fallback` is passed
 * to `request()`: a failed money read must surface as a failure, never as an empty plan.
 */

const enc = encodeURIComponent
const post = (body?: unknown): RequestInit => (body === undefined ? { method: "POST" } : { method: "POST", body: JSON.stringify(body) })
const sub = (id: string) => `/billing/subscriptions/${enc(id)}`

function withBeneficiary(path: string, beneficiaryId: string | null): string {
  return beneficiaryId ? `${path}?beneficiaryId=${enc(beneficiaryId)}` : path
}

export const billingApi = {
  catalogue: () => request<WireCatalogue>("/billing/catalogue"),
  summary: (beneficiaryId: string | null) => request<WireBillingSummary>(withBeneficiary("/billing/summary", beneficiaryId)),
  startSubscriptionCheckout: (body: SubscriptionCheckoutRequest) =>
    request<WireSubscriptionCheckout>("/billing/subscriptions/checkout", post(body)),
  startPackCheckout: (body: PackCheckoutRequest) => request<WireCheckout>("/billing/checkout/pack", post(body)),
  payment: (paymentId: string) => request<WirePaymentStatus>(`/billing/payments/${enc(paymentId)}`),
  upgradeQuote: (subscriptionId: string, planTierId: string) =>
    request<WireQuote>(`${sub(subscriptionId)}/upgrade/quote`, post({ planTierId })),
  upgrade: (subscriptionId: string, planTierId: string) => request<WireCharge>(`${sub(subscriptionId)}/upgrade`, post({ planTierId })),
  downgrade: (subscriptionId: string, planTierId: string) =>
    request<WireSubscription>(`${sub(subscriptionId)}/downgrade`, post({ planTierId })),
  cancel: (subscriptionId: string) => request<WireSubscription>(`${sub(subscriptionId)}/cancel`, post()),
  receipts: () => request<WireReceiptList>("/billing/receipts"),
  autoTopup: (beneficiaryId: string | null) => request<WireAutoTopup>(withBeneficiary("/billing/auto-topup", beneficiaryId)),
  saveAutoTopup: (body: AutoTopupUpdate) => request<WireAutoTopup>("/billing/auto-topup", { method: "PUT", body: JSON.stringify(body) }),
  cards: () => request<WireSavedCardList>("/billing/cards"),
  seatQuote: (subscriptionId: string, seats: number) => request<WireQuote>(`${sub(subscriptionId)}/seats/quote`, post({ seats })),
  addSeats: (subscriptionId: string, seats: number) => request<WireCharge>(`${sub(subscriptionId)}/seats`, post({ seats })),
  /** `extraSeats` is the new total from the next renewal, not a delta (06 `SeatReductionRequest`). */
  reduceSeats: (subscriptionId: string, extraSeats: number) =>
    request<WireSeats>(`${sub(subscriptionId)}/seats/pending`, { method: "PUT", body: JSON.stringify({ extraSeats }) }),
}

export const billingKeys = {
  all: ["billing"] as const,
  catalogue: ["billing", "catalogue"] as const,
  summary: (beneficiaryId: string | null) => ["billing", "summary", beneficiaryId ?? "me"] as const,
  payment: (paymentId: string) => ["billing", "payment", paymentId] as const,
  receipts: ["billing", "receipts"] as const,
  autoTopup: (beneficiaryId: string | null) => ["billing", "auto-topup", beneficiaryId ?? "me"] as const,
  cards: ["billing", "cards"] as const,
}

/** Query prefixes that move when money moves: billing data, and usage (estimates, meter, history). */
export const BILLING_SUCCESS_KEYS = [billingKeys.all, usageKeys.all] as const

/** Call after any billing success (a paid return, a pack, a plan or seat change, an auto top-up). */
export function invalidateBilling(queryClient: QueryClient): void {
  for (const queryKey of BILLING_SUCCESS_KEYS) void queryClient.invalidateQueries({ queryKey })
}

export const PAYMENT_POLL_MS = 2000
export const PAYMENT_POLL_LIMIT_MS = 180_000

/**
 * Poll while the payment is unconfirmed, for at most three minutes, and never after a failed
 * fetch (the screen shows the error with a retry instead of hammering a failing route). Pure,
 * for tests.
 */
export function nextPaymentPoll(
  status: PaymentStatus | undefined,
  startedAt: number,
  now: number,
  fetchFailed = false,
): number | false {
  if (fetchFailed) return false
  if (status !== undefined && status !== "created" && status !== "pending") return false
  return now - startedAt < PAYMENT_POLL_LIMIT_MS ? PAYMENT_POLL_MS : false
}

/** True once the time limit, not a terminal status, ended polling on an unconfirmed payment. */
export function pollingExpired(status: PaymentStatus | undefined, startedAt: number, now: number): boolean {
  return (status === "created" || status === "pending") && now - startedAt >= PAYMENT_POLL_LIMIT_MS
}

/** One catalogue request; each audience is a `select` over it. */
export function useCatalogue(audience: Audience): UseQueryResult<Catalogue, Error> {
  return useQuery({ queryKey: billingKeys.catalogue, queryFn: billingApi.catalogue, select: (w) => toCatalogue(w, audience) })
}

export function useBillingSummary(beneficiaryId: string | null = null): UseQueryResult<BillingSummary, Error> {
  return useQuery({ queryKey: billingKeys.summary(beneficiaryId), queryFn: () => billingApi.summary(beneficiaryId), select: toBillingSummary })
}

/**
 * Pure poll-clock logic behind `usePaymentStatus`, split out so it is testable without a DOM.
 * The clock belongs to one payment id and restarts when the id changes.
 */
export interface PaymentPollClock {
  id: string | null
  startedAt: number
}

export function startPollClock(id: string | null, now: number): PaymentPollClock {
  return { id, startedAt: now }
}

/** The same clock while the id is unchanged, a fresh one when it changed. */
export function syncPollClock(clock: PaymentPollClock, id: string | null, now: number): PaymentPollClock {
  return clock.id === id ? clock : startPollClock(id, now)
}

/** The `refetchInterval` answer for the current clock, status and fetch outcome. */
export function pollInterval(clock: PaymentPollClock, status: PaymentStatus | undefined, now: number, errored: boolean): number | false {
  return nextPaymentPoll(status, clock.startedAt, now, errored)
}

/** Fires `onExpire` when the time limit ends polling on an unconfirmed payment. Returns the cleanup. */
export function schedulePollExpiry(
  clock: PaymentPollClock,
  status: PaymentStatus | undefined,
  now: number,
  onExpire: () => void,
): () => void {
  if (status !== "created" && status !== "pending") return () => undefined
  const timer = setTimeout(onExpire, Math.max(0, clock.startedAt + PAYMENT_POLL_LIMIT_MS - now) + 1)
  return () => clearTimeout(timer)
}

/**
 * `GET /billing/payments/{id}`, polled every 2s while `created`/`pending`, for three minutes at
 * most (spec §5.1 step 5), never after a failed fetch. `pollingStopped` turns true, through a
 * timer that re-renders at the limit, so the screen can say polling gave up.
 */
export function usePaymentStatus(paymentId: string | null): UseQueryResult<PaymentStatusView, Error> & { pollingStopped: boolean } {
  const [stored, setStored] = useState(() => startPollClock(paymentId, Date.now()))
  const clock = syncPollClock(stored, paymentId, Date.now())
  if (clock !== stored) setStored(clock)
  const [, rerender] = useState(0)
  const query = useQuery({
    queryKey: billingKeys.payment(paymentId ?? ""),
    queryFn: () => billingApi.payment(paymentId ?? ""),
    enabled: paymentId !== null,
    refetchInterval: (q) => pollInterval(clock, q.state.data?.status, Date.now(), q.state.status === "error"),
  })
  const status = query.data?.status
  useEffect(() => schedulePollExpiry(clock, status, Date.now(), () => rerender((n) => n + 1)), [clock, status])
  return Object.assign(query, { pollingStopped: pollingExpired(status, clock.startedAt, Date.now()) })
}

export function useStartSubscriptionCheckout(): UseMutationResult<CheckoutResponse, Error, SubscriptionCheckoutRequest> {
  return useMutation({
    mutationFn: async (body) => {
      const w = await billingApi.startSubscriptionCheckout(body)
      return { paymentId: w.paymentId, checkoutUrl: w.checkoutUrl }
    },
  })
}

export function useStartPackCheckout(): UseMutationResult<CheckoutResponse, Error, PackCheckoutRequest> {
  return useMutation({ mutationFn: billingApi.startPackCheckout })
}

type PlanTarget = { subscriptionId: string; planTierId: string }

export function useUpgradeQuote(): UseMutationResult<Quote, Error, PlanTarget> {
  return useMutation({ mutationFn: ({ subscriptionId, planTierId }) => billingApi.upgradeQuote(subscriptionId, planTierId) })
}

/** 202 `ChargeDTO`: poll its `paymentId` (spec §5.3). */
export function useUpgrade(): UseMutationResult<WireCharge, Error, PlanTarget> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ subscriptionId, planTierId }) => billingApi.upgrade(subscriptionId, planTierId),
    onSuccess: () => invalidateBilling(qc),
  })
}

/** Returns the subscription; the downgrade applies at its `currentPeriodEnd`. */
export function useDowngrade(): UseMutationResult<WireSubscription, Error, PlanTarget> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ subscriptionId, planTierId }) => billingApi.downgrade(subscriptionId, planTierId),
    onSuccess: () => invalidateBilling(qc),
  })
}

/** Returns the subscription; access ends at its `currentPeriodEnd`. */
export function useCancelSubscription(): UseMutationResult<WireSubscription, Error, { subscriptionId: string }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ subscriptionId }) => billingApi.cancel(subscriptionId),
    onSuccess: () => invalidateBilling(qc),
  })
}

export function useReceipts(): UseQueryResult<{ receipts: Receipt[] }, Error> {
  return useQuery({ queryKey: billingKeys.receipts, queryFn: billingApi.receipts })
}

export function useAutoTopup(beneficiaryId: string | null = null): UseQueryResult<AutoTopupSettings, Error> {
  return useQuery({ queryKey: billingKeys.autoTopup(beneficiaryId), queryFn: () => billingApi.autoTopup(beneficiaryId), select: toAutoTopup })
}

export function useSaveAutoTopup(): UseMutationResult<WireAutoTopup, Error, AutoTopupUpdate> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: billingApi.saveAutoTopup,
    onSuccess: (data, body) => {
      qc.setQueryData(billingKeys.autoTopup(body.beneficiaryId), data)
      invalidateBilling(qc)
    },
  })
}

export function useSavedCards(): UseQueryResult<{ cards: SavedCardView[] }, Error> {
  return useQuery({
    queryKey: billingKeys.cards,
    queryFn: billingApi.cards,
    select: (w) => ({ cards: w.cards.flatMap((c) => toSavedCard(c) ?? []) }),
  })
}

export function useSeatQuote(): UseMutationResult<Quote, Error, { subscriptionId: string; seats: number }> {
  return useMutation({ mutationFn: ({ subscriptionId, seats }) => billingApi.seatQuote(subscriptionId, seats) })
}

export function useAddSeats(): UseMutationResult<MerchantChargeStarted, Error, { subscriptionId: string; seats: number }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ subscriptionId, seats }) => billingApi.addSeats(subscriptionId, seats),
    onSuccess: () => {
      invalidateBilling(qc)
      void qc.invalidateQueries({ queryKey: ["team"] })
    },
  })
}

export function useReduceSeats(): UseMutationResult<SeatReductionResult, Error, { subscriptionId: string; extraSeats: number }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ subscriptionId, extraSeats }) => billingApi.reduceSeats(subscriptionId, extraSeats),
    onSuccess: () => {
      invalidateBilling(qc)
      void qc.invalidateQueries({ queryKey: ["team"] })
    },
  })
}
