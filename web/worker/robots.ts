// Edge rules for the public tutor surface (SPEC §b.5 rev 3, decision row 17,
// THREAT-MODEL SC-18 and SC-26).
//
// 1. Search indexing of tutor pages. A listed tutor's public card is indexable
//    by default and the tutor can opt out, so for `/tutors/{id}` the worker
//    asks P2 (`GET /api/public/tutors/{id}`) and lets the card be indexed ONLY
//    when that answers 200 with `indexable === true`. Every other outcome
//    (opted out, 404, any other status, network error, timeout, unparseable
//    JSON, a missing or non-boolean field, a path that is not exactly one UUID
//    segment) sends `noindex, nofollow`: fail closed. The directory `/tutors`
//    lists opted-out tutors too, so it is never indexed (`noindex, follow`
//    lets crawlers reach the cards).
//
//    The body is always `env.ASSETS.fetch(request)`, the SPA shell through
//    wrangler.jsonc's `not_found_handling`; this module never builds HTML. The
//    five security headers are set by index.ts's `applySecurityHeaders`, the
//    same helper the /api/* path uses, because Cloudflare does not apply
//    `public/_headers` to responses a Worker produces.
//
// 2. A `caches.default` read-through for the public, unauthenticated GETs
//    (P1-P3), shared by the /api/* proxy and the card lookup. It shields
//    Postgres from repeated identical requests; it is not a rate limit.
import type { Env } from "./index";

/** `X-Robots-Tag` for the directory page. */
export const DIRECTORY_ROBOTS_TAG = "noindex, follow";
/** `X-Robots-Tag` for every tutor page that is not a confirmed indexable card. */
export const NOINDEX_ROBOTS_TAG = "noindex, nofollow";
/** The card lookup gives up after this long and the card stays noindex. */
export const TUTOR_LOOKUP_TIMEOUT_MS = 1500;
/** How long the edge keeps a public response; an opt-out reaches the edge
 * within this many seconds. */
export const PUBLIC_CACHE_TTL_SECONDS = 60;

// Exactly one segment, canonical 8-4-4-4-12 hex in either case. Anything else
// under /tutors/ never reaches the backend.
const CARD_PATH = /^\/tutors\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

/** The pages wrangler.jsonc's `run_worker_first` sends here: `/tutors` and
 * `/tutors/*`, matched exactly as those two patterns match. */
export function isTutorPagePath(pathname: string): boolean {
	return pathname === "/tutors" || pathname.startsWith("/tutors/");
}

/** The GETs that go through the read-through: `/api/public/tutors*` (P1, P2)
 * and `/api/public/tutoring-areas` (P3). Nothing else under /api/* is public. */
export function isPublicCacheablePath(pathname: string): boolean {
	return (
		pathname === "/api/public/tutors" ||
		pathname.startsWith("/api/public/tutors/") ||
		pathname === "/api/public/tutoring-areas"
	);
}

/**
 * Read-through over `caches.default`, keyed on `cacheUrl` alone.
 *
 * The key is a bare GET with no headers, so nothing the client sends
 * (`If-None-Match`, `Range`, cookies) can shape what the cache answers. A
 * response is stored only when it is a 200 that does not mark itself
 * `private` or `no-store`, and it is stored with this module's own TTL. A
 * cache that fails to read or write never fails the request.
 */
export async function readThroughPublicCache(
	cacheUrl: string,
	fetchUpstream: () => Promise<Response>,
): Promise<Response> {
	const cache = caches.default;
	const key = new Request(cacheUrl, { method: "GET" });
	try {
		const hit = await cache.match(key);
		if (hit) return hit;
	} catch {
		// An unreadable cache is a miss.
	}
	const res = await fetchUpstream();
	const cacheControl = res.headers.get("Cache-Control") ?? "";
	if (res.status === 200 && !/\b(?:private|no-store)\b/i.test(cacheControl)) {
		const copy = res.clone();
		const stored = new Response(copy.body, copy);
		stored.headers.set("Cache-Control", `public, max-age=${PUBLIC_CACHE_TTL_SECONDS}`);
		try {
			await cache.put(key, stored);
		} catch {
			// Not stored; the next request asks the backend again.
		}
	}
	return res;
}

/** The `X-Robots-Tag` a tutor page gets, or `null` for an indexable card. */
async function robotsTagFor(url: URL, env: Pick<Env, "BACKEND_URL">): Promise<string | null> {
	if (url.pathname === "/tutors") return DIRECTORY_ROBOTS_TAG;
	const card = CARD_PATH.exec(url.pathname);
	if (!card) return NOINDEX_ROBOTS_TAG;
	return (await lookupIndexable(card[1], url, env)) ? null : NOINDEX_ROBOTS_TAG;
}

/**
 * True only if P2 answers 200 with `indexable === true` within the timeout.
 *
 * The request is built from scratch: method GET, no cookie, no
 * `Authorization`, no client header at all, one fixed path template, and a
 * redirect is an answer rather than a hop. So it is not an open proxy and the
 * backend learns nothing about the visitor. It reads through the same cache
 * as a browser's own P2 call: the key is this site's public P2 URL.
 */
async function lookupIndexable(
	tutorId: string,
	pageUrl: URL,
	env: Pick<Env, "BACKEND_URL">,
): Promise<boolean> {
	const path = `/api/public/tutors/${tutorId}`;
	const controller = new AbortController();
	let timer: ReturnType<typeof setTimeout> | undefined;
	const timedOut = new Promise<false>((resolve) => {
		timer = setTimeout(() => {
			controller.abort();
			resolve(false);
		}, TUTOR_LOOKUP_TIMEOUT_MS);
	});
	const answer = (async (): Promise<boolean> => {
		try {
			const res = await readThroughPublicCache(new URL(path, pageUrl).href, () =>
				fetch(
					new Request(new URL(path, env.BACKEND_URL).href, {
						method: "GET",
						redirect: "manual",
						signal: controller.signal,
					}),
				),
			);
			if (res.status !== 200) return false;
			const body: unknown = await res.json();
			return typeof body === "object" && body !== null && "indexable" in body && body.indexable === true;
		} catch {
			return false;
		}
	})();
	try {
		// The race bounds the whole lookup, body included. On timeout the abort
		// cancels the subrequest, so the losing branch settles as `false`.
		return await Promise.race([answer, timedOut]);
	} finally {
		if (timer !== undefined) clearTimeout(timer);
	}
}

/**
 * `/tutors` and `/tutors/*`: the SPA shell from `ASSETS`, with the robots
 * decision as its only change. The decision and the asset fetch run together.
 */
export async function handleTutorPage(
	request: Request,
	env: Pick<Env, "ASSETS" | "BACKEND_URL">,
): Promise<Response> {
	const [robotsTag, asset] = await Promise.all([
		robotsTagFor(new URL(request.url), env),
		env.ASSETS.fetch(request),
	]);
	// A binding's response has immutable headers; copy it to change them.
	const page = new Response(asset.body, asset);
	if (robotsTag === null) {
		// Indexable: no X-Robots-Tag, whatever the asset response carried.
		page.headers.delete("X-Robots-Tag");
	} else {
		page.headers.set("X-Robots-Tag", robotsTag);
	}
	return page;
}
