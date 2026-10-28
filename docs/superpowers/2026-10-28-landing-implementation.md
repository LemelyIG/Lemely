# Brand landing page implementation

Implemented on `feat/brand-landing-page-ui`, branched from the existing `feat/brand-landing-page` checkout. Unrelated working-tree edits were preserved.

The public `/landing` and signed-out `/` use the supplied Abyss identity: local Bricolage Grotesque and Schibsted Grotesk fonts, Clip Letters branding, workshop chart/feature artwork, and Binny. Marketing tokens are scoped so authenticated portals keep their current appearance.

Configured shadcn/ui for the existing Vite/Tailwind 4 project and aliases. Installed official Sheet, Accordion, Carousel and Toggle Group components, adapted their imports to the existing cn utility and Phosphor icons, and preserved the existing Button, Tabs and Textarea APIs. Generated primitives follow the repository's focus, elevation, logical-direction and native interaction rules.

Reusable sections cover the hero, proof metrics, continuous dark teacher band, marking walkthrough, feature collection, desktop Binny conversation, mobile FAQ and closing actions. Mobile decks support swipe, arrow buttons and keyboard navigation. The walkthrough supports all three steps, question selection, confidence and local illustrative teacher review.

Signup, login, parent access and data-handling routes are preserved. Demo/contact actions open email at contact@lemelyig.com. FAQ answers are deterministic; contact and report illustrations do not claim delivery. Google Classroom remains labeled coming soon. No deployment, new messaging backend or application-wide component migration was performed.

## Verification

- `npm test`: 205 files, 3,650 tests passed.
- `npm run typecheck`: passed.
- `npm run lint`: zero errors; 172 warnings, including existing export warnings; all 20 native invariants passed.
- `npm run build`: passed; all 165 chunks within the bundle budget.
- Dedicated Playwright suite: eight desktop/mobile tests passed, including keyboard FAQ/review, navigation, contact destinations, axe accessibility scan, and overflow checks at 320, 375, 390, 414, 768, 1280 and 1440px.
- Fresh code review identified two visual omissions; regression coverage was added, both were corrected, and follow-up review found no remaining material issue.
- `graphify update .` refreshed the local AST graph. Existing untracked graph output remains in place. Graphify reports its existing missing optional SQL parser and community-label warnings.

Preview locally with `cd web && npm run dev`, then open `/landing`.
