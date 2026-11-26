// The fill for a flashcards skeleton. SkeletonBlock's default (surface-container-low) is a well one step down from a card.
// Here the blocks sit on the surface itself: the page behind the shelf, the deck page and the review is that same tone
// (390px) or one step off it (desktop), and a native sheet (`.lm-sheet`) is the same variable, so the placeholder vanished
// and loading read as a blank screen. One step further down is the mock's `--sh` fill (t.css `.sk`), and it holds in light
// and dark on every surface these screens use.

export const SKELETON_FILL = "bg-surface-container-high"
