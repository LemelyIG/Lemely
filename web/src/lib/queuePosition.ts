/**
 * Task 9 (C3d) · One review item's position in its (already filtered) queue
 * — the data behind `ReviewItem.tsx`'s "Item N of total" strip and its
 * Prev/Next links.
 *
 * `index` is the 0-based position of `currentId` within `ids` (display as
 * `index + 1` of `total`). `null` when `currentId` isn't in `ids` at all —
 * the same "this item fell out of the current filtered queue" case
 * `ReviewItem.tsx`'s existing `nextItemId` logic already handles by falling
 * back to "Back to queue"; the strip reuses that same signal to render
 * nothing rather than a position that would be misleading (e.g. "Item 0 of
 * 12").
 */
export function queuePosition(
  ids: readonly string[],
  currentId: string,
): { index: number; total: number; prevId: string | null; nextId: string | null } | null {
  const index = ids.indexOf(currentId)
  if (index === -1) return null
  return {
    index,
    total: ids.length,
    prevId: index > 0 ? ids[index - 1] : null,
    nextId: index < ids.length - 1 ? ids[index + 1] : null,
  }
}
