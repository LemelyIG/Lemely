/*
 * Web Share, with an honest copy-link fallback (Task 7 / B5a).
 *
 * There is no result download anywhere on `PaperResult` at `c70dd38d` for
 * this to fall back to, so copy-link is the one honest fallback available:
 * `shareResult` never rejects and never reports success it did not have —
 * it returns `"unavailable"` only when neither `navigator.share` nor
 * `navigator.clipboard.writeText` exist.
 *
 * Both functions take an injected `navigator`-shaped object (default: the
 * real global) so this file is testable under vitest's jsdom-less
 * `environment: "node"` (`vitest.config.ts`), matching `haptics.ts`.
 */

/** The slice of `Navigator` this module needs — optional, unlike the real
 * DOM type (which declares `share`/`canShare`/`clipboard` as always
 * present), because most engines genuinely lack them and an injected test
 * fake should not have to stub methods it will never be asked for. */
interface ShareCapableNavigator {
  share?: (data?: ShareData) => Promise<void>
  canShare?: (data?: ShareData) => boolean
}

interface ClipboardCapableNavigator {
  clipboard?: { writeText: (data: string) => Promise<void> }
}

type ShareResultNavigator = ShareCapableNavigator & ClipboardCapableNavigator

export interface ShareResultData {
  url: string
  title: string
  text: string
}

const globalNavigator: ShareResultNavigator | undefined =
  typeof navigator === "undefined" ? undefined : navigator

/** Whether the platform can share `data` at all — `navigator.share` exists
 * and, when `canShare` also exists, agrees this particular payload is
 * shareable. An engine with `share` but no `canShare` (older Safari) is
 * taken at its word. */
export function canWebShare(data: ShareData, nav: ShareCapableNavigator | undefined = globalNavigator): boolean {
  if (typeof nav?.share !== "function") return false
  if (typeof nav.canShare === "function") return nav.canShare(data)
  return true
}

/**
 * Share `data`, falling back to copying the link when the platform can't (or
 * a native share sheet was cancelled/refused). `deps.toast` is called with a
 * plain sentence, not a full `ToastOptions` — the caller adapts it to
 * whatever toast API the screen already uses.
 */
export async function shareResult(
  data: ShareResultData,
  deps?: { nav?: ShareResultNavigator; toast?: (msg: string) => void },
): Promise<"shared" | "copied" | "unavailable"> {
  const nav = deps?.nav ?? globalNavigator

  if (canWebShare(data, nav)) {
    try {
      await nav!.share!(data)
      return "shared"
    } catch {
      // Cancelled or refused — fall through to the copy-link fallback below,
      // the same "always resolves" contract the return type promises.
    }
  }

  const clipboard = nav?.clipboard
  if (typeof clipboard?.writeText === "function") {
    try {
      await clipboard.writeText(data.url)
      deps?.toast?.("Link copied")
      return "copied"
    } catch {
      return "unavailable"
    }
  }

  return "unavailable"
}
