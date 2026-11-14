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

/**
 * The direction `html[data-direction]` gets for a navigation: the router action, unless the
 * location state names one. A "tab" tag on the destination only means something on the PUSH the tab
 * bar made. A POP that leaves an entry the tab bar made is the same tab switch undone ("tab"); any
 * other POP, including popping a drill-down pushed from a tab, is a back.
 */
export function resolveDirection(
  type: "POP" | "PUSH" | "REPLACE",
  explicit?: "back" | "tab",
  leaving?: "back" | "tab",
): "back" | "forward" | "tab" {
  if (type === "POP") return leaving === "tab" ? "tab" : "back"
  if (explicit === "tab") return type === "PUSH" ? "tab" : navigationDirection(type)
  return explicit ?? navigationDirection(type)
}
