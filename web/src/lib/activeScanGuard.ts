/*
 * Module-level flag: whether the current portal screen (`CorrectPaper.tsx`
 * or `Grading.tsx`) holds a scan the reader hasn't submitted yet.
 * `readSharedScan()` (`sharedScan.ts`) deletes its Cache Storage entry as
 * part of reading it, so once read, a shared/launched scan lives only in
 * that screen's own React state. `UpdateToast.tsx`'s "Reload" action
 * persists indefinitely (`duration: 0`) — read this flag at click time,
 * before calling `applyUpdate()`, so a reload can't destroy an in-flight
 * scan with no recovery path.
 *
 * Plain module state, not `useSyncExternalStore` (contrast
 * `useInstallPrompt.ts`'s `deferredEvent` store): nothing here needs to
 * re-render on a change, only to be read once, at the moment the reader
 * taps "Reload".
 */
let hasUnsubmittedScan = false

export function setHasUnsubmittedScan(value: boolean): void {
  hasUnsubmittedScan = value
}

export function getUnsubmittedScanSnapshot(): boolean {
  return hasUnsubmittedScan
}
