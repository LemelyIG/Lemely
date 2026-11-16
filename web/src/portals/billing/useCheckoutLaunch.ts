import { useEffect, useState } from "react"
import type { UseMutationResult } from "@tanstack/react-query"
import type { CheckoutResponse } from "@/lib/billingTypes"
import { startCheckoutRedirect } from "@/lib/checkoutReturn"

/** What an unsafe checkout URL tells the payer; the same line the plans page uses. */
export const UNSAFE_CHECKOUT_URL = "Couldn't start checkout. Nothing was charged. Try again."

/*
 * Start a payer-present checkout from a dialog and leave for Paymob (spec §5.1 steps 3-4).
 * `redirecting` stays true from the 201 until the page actually leaves, so the button keeps its
 * loading state and a second click cannot create a second pending payment. The browser's Back
 * button can restore the page frozen mid-redirect, so a persisted `pageshow` starts over.
 * `go` is injectable for tests.
 */
export function useCheckoutLaunch<V>(
  mutation: Pick<UseMutationResult<CheckoutResponse, Error, V>, "mutate" | "reset" | "isSuccess" | "isPending" | "variables">,
  returnTo: string,
  go?: (url: string) => void,
) {
  const [unsafe, setUnsafe] = useState(false)
  const { mutate, reset } = mutation
  useEffect(() => {
    if (typeof window === "undefined") return
    const onShow = (e: PageTransitionEvent) => {
      if (!e.persisted) return
      reset()
      setUnsafe(false)
    }
    window.addEventListener("pageshow", onShow)
    return () => window.removeEventListener("pageshow", onShow)
  }, [reset])
  const launch = (variables: V) => {
    setUnsafe(false)
    mutate(variables, {
      onSuccess: (res) => {
        if (startCheckoutRedirect(res, returnTo, go)) return
        setUnsafe(true)
        reset()
      },
    })
  }
  return { launch, unsafe, redirecting: mutation.isSuccess && !unsafe }
}
