import { createElement as h, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { vi } from "vitest"

/*
 * Static-render helpers for billing component tests. The web runner is `environment: "node"`
 * with no jsdom (D3.20), so components render to markup with `react-dom/server` and hooks are
 * replaced with these fake query/mutation objects through `vi.mock`.
 */

function client(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

export function renderStatic(el: ReactElement, path = "/"): string {
  return renderToStaticMarkup(h(QueryClientProvider, { client: client() }, h(MemoryRouter, { initialEntries: [path] }, el)))
}

/** Render `el` as the element of route `pattern`, visited at `url` (for `useParams`). */
export function renderAt(el: ReactElement, pattern: string, url: string): string {
  return renderToStaticMarkup(
    h(QueryClientProvider, { client: client() }, h(MemoryRouter, { initialEntries: [url] }, h(Routes, null, h(Route, { path: pattern, element: el })))),
  )
}

const base = { refetch: () => undefined, isFetching: false, isLoading: false, isRefetching: false }

export function okQuery<T>(data: T) {
  return { ...base, status: "success" as const, fetchStatus: "idle" as const, data, error: null, isPending: false, isError: false, isSuccess: true }
}

export function pendingQuery() {
  return { ...base, status: "pending" as const, fetchStatus: "fetching" as const, data: undefined, error: null, isPending: true, isError: false, isSuccess: false, isLoading: true }
}

export function errorQuery(error: unknown) {
  return { ...base, status: "error" as const, fetchStatus: "idle" as const, data: undefined, error, isPending: false, isError: true, isSuccess: false }
}

export function fakeMutation<T = unknown>(over: Partial<{ isPending: boolean; isError: boolean; isSuccess: boolean; error: unknown; data: T }> = {}) {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: false,
    isIdle: true,
    error: null as unknown,
    data: undefined as T | undefined,
    ...over,
  }
}
