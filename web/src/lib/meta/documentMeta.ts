/*
 * Per-route document titles and descriptions (P6.5).
 *
 * ── The finding ─────────────────────────────────────────────────────────────
 *
 * **No screen in the product set a `document.title`.** All 48 routes were
 * "Lemely", from the one static `<title>` in `index.html`, for the whole build
 * and the whole redesign. Four things that follow, in rising order of how much
 * they matter:
 *
 *   - Every browser tab, every bookmark and every history entry was
 *     indistinguishable from every other. A student with their dashboard, a
 *     marked paper and a flashcard deck open has three tabs reading "Lemely".
 *   - `Ctrl+Shift+A` / tab search, which is how people with many tabs actually
 *     navigate, could not find anything in this product by name.
 *   - **A screen reader announces the document title on navigation.** In a
 *     single-page app nothing else announces that the page changed at all, so a
 *     non-sighted reader clicking through the sidebar heard "Lemely" after
 *     every single navigation and was never told where they had arrived. That
 *     makes this an accessibility defect as much as a metadata one, and it is
 *     the reason it is worth doing for authenticated screens that no crawler
 *     will ever read.
 *   - There were no `description` or `og:` tags at all, so the one genuinely
 *     public page in the product shared as a bare URL.
 *
 * ── Why `handle` rather than a hook in each screen ──────────────────────────
 *
 * The alternative is a `useDocumentTitle("...")` call at the top of all 48
 * screens. It was rejected for the reason this phase keeps re-learning: **a
 * screen no list claims is a screen no gate reads** (P4.10). A per-screen hook
 * has nothing to check against, so route number 49 ships untitled and nothing
 * says so, exactly as happened to `text-title`, to the compat layer, and to the
 * two admin portals.
 *
 * Route `handle` is react-router's own mechanism for static per-route metadata,
 * and it puts the title *in the route table*, where `tests/unit/documentMeta
 * .test.ts` can walk the tree and fail on any route that lacks one. The title
 * is then impossible to add a route without.
 *
 * ── What gets a description, and what deliberately does not ─────────────────
 *
 * Titles: every route, for the reasons above.
 *
 * Descriptions and `og:` tags: **only the routes a signed-out reader can
 * actually reach** — the landing page, both sign-in screens, and the 404.
 * Everything else is behind `RequireAuth`, so no crawler and no chat-app
 * unfurler will ever see it, and writing marketing prose into the head of a
 * teacher's review queue would be inventing copy for an audience that does not
 * exist. `index.html` carries the default for anything that does not override.
 */

/** Static metadata attached to a route's `handle`. */
export interface PageMeta {
  /**
   * The page's own name, without the product name. Sentence case, no
   * em-dash, no invented claim (§3.2 item 10).
   *
   * Dynamic routes are named for what the screen *is* ("Paper result") rather
   * than for the record it happens to be showing: the route table cannot know
   * the paper, and inventing a title from an id would be worse than a general
   * one.
   */
  title: string
  /**
   * Only for routes reachable without a session. See the module note.
   */
  description?: string
}

/** The product name, appended to every page title. */
export const SITE_NAME = "Lemely"

/**
 * The head `index.html` ships, and what a route with no override falls back to.
 * Kept here as well as in the HTML because this is what a client-side
 * navigation has to restore; the two are pinned equal by the unit test.
 */
export const DEFAULT_TITLE = "Lemely, marking for CAIE past papers"
export const DEFAULT_DESCRIPTION =
  "Lemely marks a photographed or uploaded CAIE past-paper attempt against the official marking scheme, with method marks, and returns per-question marks, a grade, and the topics to work on."

/**
 * Type guard for a route handle carrying page metadata.
 *
 * React-router types `handle` as `unknown`, so this is the boundary where an
 * untyped value becomes a `PageMeta`. It checks the field it actually uses
 * rather than trusting the shape.
 */
export function isPageMeta(handle: unknown): handle is PageMeta {
  return (
    typeof handle === "object" &&
    handle !== null &&
    "title" in handle &&
    typeof (handle as { title: unknown }).title === "string" &&
    (handle as { title: string }).title.length > 0
  )
}

/**
 * Picks the metadata for the page from a route match chain.
 *
 * **Deepest wins.** A match chain for `/teacher/review/abc` is [teacher layout,
 * review item], and the leaf is what the reader is actually looking at; the
 * layout's own handle (if it ever gains one) is the fallback for its index
 * route. Iterating from the end and stopping at the first hit is what makes a
 * portal's `*` catch-all able to name itself "Page not found" while its parent
 * still names the portal.
 */
export function pageMetaFromMatches(matches: readonly { handle?: unknown }[]): PageMeta | null {
  for (let i = matches.length - 1; i >= 0; i--) {
    const handle = matches[i]?.handle
    if (isPageMeta(handle)) return handle
  }
  return null
}

/**
 * The string that goes in the tab.
 *
 * `·` and not an em-dash: §3.2 item 10 bans em-dashes in UI copy, and a tab
 * title is UI copy. A route whose title already *is* the product name (the
 * landing page) is not suffixed, because "Lemely · Lemely" is what that rule
 * would otherwise produce.
 */
export function formatTitle(meta: PageMeta | null): string {
  if (!meta) return DEFAULT_TITLE
  if (meta.title === SITE_NAME || meta.title.startsWith(`${SITE_NAME},`)) return meta.title
  return `${meta.title} · ${SITE_NAME}`
}

/**
 * Writes one `<meta name=... content=...>`, creating it if the document has
 * none.
 *
 * `property` for the `og:` tags and `name` for the rest is not a stylistic
 * choice: Open Graph is RDFa and scrapers look for `property`, while the plain
 * description is HTML5 and wants `name`. Getting this wrong produces tags that
 * look right in the inspector and are ignored by every consumer.
 */
function setMetaTag(attr: "name" | "property", key: string, content: string): void {
  let tag = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`)
  if (!tag) {
    tag = document.createElement("meta")
    tag.setAttribute(attr, key)
    document.head.appendChild(tag)
  }
  tag.setAttribute("content", content)
}

/**
 * Applies a match chain's metadata to the live document.
 *
 * Called once at startup and again on every router state change (see
 * `App.tsx`). It always writes both the title and the description, including
 * when falling back to the defaults, so navigating from the landing page into
 * the app does not leave the landing page's description behind in the head.
 */
export function applyDocumentMeta(matches: readonly { handle?: unknown }[]): void {
  const meta = pageMetaFromMatches(matches)
  const title = formatTitle(meta)
  const description = meta?.description ?? DEFAULT_DESCRIPTION

  document.title = title
  setMetaTag("name", "description", description)
  // Kept in step with the title so a link shared from a public page unfurls as
  // that page rather than as the site root.
  setMetaTag("property", "og:title", title)
  setMetaTag("property", "og:description", description)
}
