/*
 * Which pathname each history entry of this session holds, by React Router's entry index.
 *
 * The browser does not let a page read its own history, so the shell keeps its own record (RootOutlet
 * writes it on every location change). The active-tab re-tap uses it to pop a drilled-in page back to
 * the tab root by going back, instead of adding an entry: [root, detail] then re-tap should end at
 * [root], not [root, detail, root] and not [root, root].
 */
const paths = new Map<number, string>()

export function recordHistoryPath(idx: number | undefined, pathname: string): void {
  if (typeof idx === "number") paths.set(idx, pathname)
}

const within = (path: string, root: string) => path === root || path.startsWith(`${root}/`)

/**
 * How many entries back is the tab root, when it sits behind `cur` with only that root's own pages
 * (the drill run) in between. Null when it is not there: a deep link, or another tab's page in the way.
 */
export function stepsBackToRoot(cur: number | undefined, root: string): number | null {
  if (typeof cur !== "number") return null
  for (let idx = cur - 1; idx >= 0; idx--) {
    const path = paths.get(idx)
    if (path === undefined || !within(path, root)) return null
    if (path === root) return cur - idx
  }
  return null
}
