// The Worker half of the Cloudflare deploy: Workers Static Assets serves the
// built SPA directly for every request (see wrangler.jsonc's `not_found_handling:
// "single-page-application"`), and the platform router only invokes THIS
// script for paths matching `assets.run_worker_first` (`/api/*` — see
// wrangler.jsonc). Every request this fetch handler sees is therefore
// already an API call.
//
// This reverse-proxies /api/* to the Cloud Run backend so the browser only
// ever talks to ONE origin (lemelyig.com / staging.lemelyig.com) — the exact
// same-origin, no-CORS shape docs/deployment.md already documents for the
// nginx-fronted local/Docker deploy (see web/nginx.conf), just with
// Cloudflare standing in for nginx. lemely/web/app.py installs no
// CORSMiddleware and this preserves that: the browser never makes a
// cross-origin request, and a Worker's own `fetch()` is a server-to-server
// call the browser's CORS policy never sees.
//
// Streaming passes straight through unbuffered, which the correction
// pipeline's SSE progress endpoints need (web/nginx.conf sets
// `proxy_buffering off` for the same reason).
export interface Env {
	BACKEND_URL: string;
}

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const url = new URL(request.url);
		const target = new URL(url.pathname + url.search, env.BACKEND_URL);

		// `new Request(url, request)` clones method/headers/body from `request`
		// (standard Fetch API constructor behaviour) while pointing at the new
		// URL; the resulting `.headers` is a fresh, independently-mutable
		// Headers instance, so the deletes/sets below don't touch the original.
		const proxyRequest = new Request(target, request);

		// Drop the inbound Host header rather than forward
		// "lemelyig.com"/"staging.lemelyig.com" to Cloud Run — omitting it lets
		// fetch() set the correct Host for `target` itself (the backend's
		// *.run.app hostname), which is what Cloud Run's front end routes on.
		proxyRequest.headers.delete("host");

		// Mirror what nginx.conf sets for the same reverse-proxy hop, so the
		// backend sees an equivalent client IP / scheme regardless of which
		// proxy fronts it. CF-Connecting-IP is Cloudflare's edge-verified
		// client IP (request.headers can't be spoofed past the edge).
		const clientIp = request.headers.get("CF-Connecting-IP");
		if (clientIp) {
			proxyRequest.headers.set("X-Real-IP", clientIp);
			proxyRequest.headers.set("X-Forwarded-For", clientIp);
		}
		proxyRequest.headers.set("X-Forwarded-Proto", "https");

		// `new Response(res.body, res)` streams `res.body` through unread rather
		// than buffering it, so the SSE progress endpoints this comment block
		// already describes keep streaming — only the header set changes.
		const res = await fetch(proxyRequest);
		const out = new Response(res.body, res);
		// A7 review fix (addendum L1): was only nosniff + Referrer-Policy — the
		// other three headers `public/_headers`/`nginx.conf` both set were
		// missing on this path entirely, so the Cloudflare deploy target wasn't
		// actually equivalent to the other two despite the ledger claiming it
		// was. Same five values as the other two deploy targets.
		out.headers.set("X-Content-Type-Options", "nosniff");
		out.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
		out.headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
		out.headers.set(
			"Permissions-Policy",
			"camera=(self), microphone=(), geolocation=(), interest-cohort=()",
		);
		out.headers.set(
			"Content-Security-Policy",
			"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
		);
		return out;
	},
} satisfies ExportedHandler<Env>;
