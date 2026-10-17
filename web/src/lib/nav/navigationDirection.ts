/*
 * Packet B2b · which way a screen's View Transition should read.
 *
 * `react-router`'s `useNavigationType()` reports the router action, not a
 * spatial direction — this is the one-line translation `RootOutlet` uses to
 * set `html[data-direction]`, which `index.css`'s `::view-transition-*`
 * rules read to pick which way the outgoing/incoming screen slides.
 *
 * `POP` is a browser back/forward; both `PUSH` and `REPLACE` are the app
 * navigating forward on its own initiative (a link, a redirect), so both
 * read as `"forward"`. `POP` cannot itself distinguish "back" from "forward
 * again" — the History API does not say which direction a POP moved — so
 * this treats every POP as `"back"`, matching `BackControl` and the browser
 * back gesture, the two things that actually trigger one.
 */
export function navigationDirection(type: "POP" | "PUSH" | "REPLACE"): "back" | "forward" {
  return type === "POP" ? "back" : "forward"
}
