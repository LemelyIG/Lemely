/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — a list of C-23 cards under a calm filter bar; the one decision is that paging is a chain of pages, so Load more never loses the reader's place. */
import { useEffect, useRef, useState, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState, type QueryStateQuery } from "@/components/ui/query-state"
import { SkeletonLine } from "@/components/ui/skeleton"
import { TutorCard } from "@/components/ui/tutor-card"
import { DirectoryFilters } from "@/components/tutoring/directory-filters"
import { usePublicTutoringAreas, usePublicTutors, useTutorDirectory } from "@/lib/hooks/useTutoringApi"
import {
  DIRECTORY_EMPTY_HEADING,
  EMPTY_FILTERS,
  PLATFORM_EMPTY_HEADING,
  directoryQuery,
  filtersToSearchParams,
  hasActiveFilters,
  type Audience,
  type DirectoryFilterState,
} from "@/lib/tutoring/discovery"
import type { DirectoryFacets, PublicDirectoryPage } from "@/lib/tutoringTypes"

/*
 * Directory view (SPEC §d, G-16 and S-33; P-07 mounts it again in the parent
 * shell). Filters, then C-23 cards, then "Load more".
 *
 * ── Paging is a chain of pages ──────────────────────────────────────────────
 *
 * The API is cursor-paged and T11's hooks fetch one page per call. Rather than
 * keep a growing list in state (and have to merge, de-duplicate and re-key it
 * when a filter changes), each page is its own small component that fetches
 * its cursor and renders its cards; the last one offers the button that mounts
 * the next. A filter change changes the `key` of the whole chain, so it starts
 * again from the first page. Pages already loaded stay in react-query's cache,
 * so going back to a filter is instant.
 *
 * Focus: "Load more" disappears when it is pressed (the next page replaces it),
 * so focus would fall to the page. The first card of the new page takes it
 * instead, and a polite status line says how many tutors the first page shows.
 *
 * States, all inside the list's own space (SPEC §d rules): skeleton cards while
 * a page loads, a retry on a failed page (the earlier pages stay), the offline
 * state when the connection is gone, "No tutors match these filters yet." with
 * "Clear filters" when filters hide everything, and "Tutors are being
 * reviewed. Check back soon." when the platform has no listed tutor at all.
 */

type CardList = PublicDirectoryPage

function CardSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2" aria-label="Loading tutors" role="status">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-5">
          <SkeletonLine announce={false} className="h-5" width="55%" />
          <SkeletonLine announce={false} width="90%" />
          <SkeletonLine announce={false} width="70%" />
          <SkeletonLine announce={false} className="h-6" width="40%" />
        </div>
      ))}
    </div>
  )
}

interface PageCardsProps {
  page: CardList
  tutorPath: (tutorId: string) => string
  focusFirst: boolean
  /** Offer "Load more": this page has a next one and it is not on screen yet. */
  canLoadMore: boolean
  onLoadMore: (cursor: string) => void
  showCount: boolean
}

function PageCards({ page, tutorPath, focusFirst, canLoadMore, onLoadMore, showCount }: PageCardsProps) {
  const listRef = useRef<HTMLUListElement>(null)
  useEffect(() => {
    if (focusFirst) listRef.current?.querySelector<HTMLElement>("a")?.focus()
    // Once, when this page first has cards on screen.
  }, [focusFirst])

  return (
    <>
      {showCount ? (
        <p className="sr-only" role="status">
          {page.items.length === 1 ? "1 tutor shown" : `${page.items.length} tutors shown`}
          {page.nextCursor ? ". More are available." : "."}
        </p>
      ) : null}
      <ul ref={listRef} className="m-0 grid list-none grid-cols-1 gap-4 p-0 lg:grid-cols-2">
        {page.items.map((tutor) => (
          <li key={tutor.tutorId} className="flex">
            <TutorCard tutor={tutor} to={tutorPath(tutor.tutorId)} headingAs="h2" className="w-full" />
          </li>
        ))}
      </ul>
      {canLoadMore && page.nextCursor ? (
        <div className="flex justify-center pt-2">
          <Button variant="secondary" onClick={() => onLoadMore(page.nextCursor as string)}>
            Load more
          </Button>
        </div>
      ) : null}
    </>
  )
}

interface PageProps {
  audience: Audience
  filters: DirectoryFilterState
  cursor: string | null
  index: number
  tutorPath: (tutorId: string) => string
  onLoadMore: (cursor: string) => void
  onFacets: (facets: DirectoryFacets) => void
  onClear: () => void
  /** Whether the next page is already on screen, so this page offers no button. */
  followed: boolean
}

function PageBody({
  query,
  index,
  filters,
  audience,
  tutorPath,
  onLoadMore,
  onFacets,
  onClear,
  followed,
}: PageProps & { query: QueryStateQuery<CardList> }) {
  const facets = (query.data as CardList | undefined)?.facets ?? null
  useEffect(() => {
    if (facets) onFacets(facets)
  }, [facets, onFacets])

  const filtered = hasActiveFilters(filters, audience)
  return (
    <QueryState
      query={query}
      skeleton={<CardSkeleton />}
      error={{ heading: "We couldn't load the tutors", retryLabel: "Try again" }}
      isEmpty={(data) => index === 0 && data.items.length === 0}
      empty={
        filtered ? (
          <EmptyState
            heading={DIRECTORY_EMPTY_HEADING}
            action={{ label: "Clear filters", onClick: onClear }}
          />
        ) : (
          <EmptyState heading={PLATFORM_EMPTY_HEADING} />
        )
      }
    >
      {(data) => (
        <PageCards
          page={data}
          tutorPath={tutorPath}
          focusFirst={index > 0}
          canLoadMore={!followed}
          showCount={index === 0}
          onLoadMore={onLoadMore}
        />
      )}
    </QueryState>
  )
}

function PublicPage(props: PageProps) {
  const query = usePublicTutors(directoryQuery(props.filters, "public", props.cursor))
  return <PageBody {...props} query={query} />
}

function MemberPage(props: PageProps) {
  const query = useTutorDirectory(directoryQuery(props.filters, "member", props.cursor))
  return <PageBody {...props} query={query} />
}

interface ResultsProps {
  audience: Audience
  filters: DirectoryFilterState
  tutorPath: (tutorId: string) => string
  onFacets: (facets: DirectoryFacets) => void
  onClear: () => void
}

/** The chain of pages for one set of filters. Mounted with a `key` per filter set. */
function DirectoryResults({ audience, filters, tutorPath, onFacets, onClear }: ResultsProps) {
  const [cursors, setCursors] = useState<(string | null)[]>([null])
  const Page = audience === "public" ? PublicPage : MemberPage
  return (
    <div className="flex flex-col gap-4">
      {cursors.map((cursor, index) => (
        <Page
          key={cursor ?? "first"}
          audience={audience}
          filters={filters}
          cursor={cursor}
          index={index}
          tutorPath={tutorPath}
          onFacets={onFacets}
          onClear={onClear}
          followed={index < cursors.length - 1}
          onLoadMore={(next) => setCursors((list) => (list.includes(next) ? list : [...list, next]))}
        />
      ))}
    </div>
  )
}

export interface DirectoryViewProps {
  audience: Audience
  /** Where a card goes: the tutor's page in this portal. */
  tutorPath: (tutorId: string) => string
  filters: DirectoryFilterState
  onFiltersChange: (next: DirectoryFilterState) => void
  /** Rendered between the filters and the cards (S-33's ranking note, G-16's sign-in line). */
  aside?: ReactNode
  className?: string
}

export function DirectoryView({
  audience,
  tutorPath,
  filters,
  onFiltersChange,
  aside,
  className,
}: DirectoryViewProps) {
  const [facets, setFacets] = useState<DirectoryFacets | null>(null)
  const areas = usePublicTutoringAreas()
  const resultKey = filtersToSearchParams(filters, audience).toString()
  const clear = () => onFiltersChange(EMPTY_FILTERS)

  return (
    <div className={className}>
      <div className="flex flex-col gap-6">
        <DirectoryFilters
          audience={audience}
          value={filters}
          onChange={onFiltersChange}
          onClear={clear}
          subjects={facets?.subjects ?? []}
          areas={areas.data?.items ?? facets?.areas ?? []}
        />
        {aside}
        <DirectoryResults
          key={resultKey}
          audience={audience}
          filters={filters}
          tutorPath={tutorPath}
          onFacets={setFacets}
          onClear={clear}
        />
      </div>
    </div>
  )
}
