import { QueryClient } from "@tanstack/react-query"

/*
 * Shared react-query client. `retry: 1` avoids hammering the backend (and the
 * Gemini-backed endpoints) on transient failures without masking real errors
 * behind an unbounded retry loop; `refetchOnWindowFocus: false` keeps portal
 * tab-switching from firing surprise network calls.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})
