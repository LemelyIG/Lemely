import { del, get, set } from "idb-keyval"
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister"

/*
 * Task 10 (B6b) — the react-query persisted cache's IndexedDB backend.
 *
 * `createAsyncStoragePersister` wants a `Storage`-shaped object
 * (`getItem`/`setItem`/`removeItem`, each `string`-in/`string`-out); IndexedDB
 * via `idb-keyval` is not that, but it stores structured-cloneable values
 * directly, so a value round-trips through it without the extra
 * `JSON.stringify`/`parse` a real `localStorage`-backed persister would need
 * — `set`/`get` just pass the string straight through. IndexedDB over
 * `localStorage` for the same reason `AuthContext.tsx`'s comment on
 * `uploadQueue.ts` doesn't apply here (this holds no credential), but does
 * apply to size: `localStorage` is capped at ~5MB and synchronous, which
 * would block the main thread on every persist of what can be a meaningfully
 * large dehydrated cache (`main.tsx`'s `PersistQueryClientProvider` persists
 * on every settled mutation/query, not just on unload).
 */
const asyncStorage = {
  getItem: async (key: string): Promise<string | null> => (await get<string>(key)) ?? null,
  setItem: async (key: string, value: string): Promise<void> => set(key, value),
  removeItem: async (key: string): Promise<void> => del(key),
}

/** Passed to `PersistQueryClientProvider`'s `persistOptions.persister` in
 * `main.tsx`. */
export const persister = createAsyncStoragePersister({
  storage: asyncStorage,
  key: "lemely-query-cache",
})
