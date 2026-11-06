/*
 * Open-state rules for the sidebar's expandable group (student subjects).
 * Design A (variant-a.js `setSubject`) makes each row its own disclosure: any
 * number can be open. The current route's row starts open; navigating into a
 * row opens it and never closes another.
 */

export function initialOpenIds(
  rowIds: readonly string[],
  currentId: string | null,
  fallbackId: string | null = null,
): Set<string> {
  if (currentId && rowIds.includes(currentId)) return new Set([currentId])
  if (fallbackId && rowIds.includes(fallbackId)) return new Set([fallbackId])
  return new Set()
}

export function toggleOpen(open: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(open)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

export function openOnNavigate(open: ReadonlySet<string>, currentId: string | null): Set<string> {
  const next = new Set(open)
  if (currentId) next.add(currentId)
  return next
}
