# Brand landing page implementation

Implemented on `feat/brand-landing-page-ui`, branched from the existing `feat/brand-landing-page` checkout. Unrelated working-tree edits were preserved.

The public `/landing` and signed-out `/` use the supplied Abyss identity: local Bricolage Grotesque and Schibsted Grotesk fonts, Clip Letters branding, workshop chart/feature artwork, and Binny. Marketing tokens are scoped so authenticated portals keep their current appearance.

Configured shadcn/ui for the existing Vite/Tailwind 4 project and aliases. Installed official Sheet, Accordion, Carousel and Toggle Group components, adapted their imports to the existing cn utility and Phosphor icons, and preserved the existing Button, Tabs and Textarea APIs. Generated primitives follow the repository's focus, elevation, logical-direction and native interaction rules.

The first pass omitted substantial reference motion. The completion pass rendered the supplied Design Component runtime and its imported ZIP artwork at desktop and mobile sizes, then used those running references to correct behavior and composition. The default reference order is hero, walkthrough, features, proof and teachers, FAQ, closing action, and footer. The closing action uses the dark Abyss surface. The alternate prototype direction is not a separate product mode.

Reusable sections include the animated five-paper hero journey, predicted grade progression, Binny hops and celebrations, original feature drawing/bar/grade/clustering/XP/content timings, one-time proof counters and dot reveals, header reading progress and active navigation, and the mobile upload shortcut. Mobile teacher features use the reference's compact grid.

The desktop walkthrough follows ordinary page scrolling through a pinned scene. Step buttons, paper questions, confidence and illustrative teacher review remain interactive. Mobile renders all three progressive sections in document flow. Reduced motion removes pinning and optional animation while keeping the complete content and keyboard controls. Mobile decks reuse shadcn Carousel with swipe, buttons, keyboard access and announced slide positions; button navigation keeps the newly selected card's title visible.

The FAQ uses deterministic responses, a typing state, Binny's supplied facial expressions, and a reusable mascot component. Automatic work pauses offscreen and in hidden tabs; effects clean up observers, listeners, animation frames, timers and Web Animations. Live reduced-motion changes restore complete artwork, and Binny's keyboard celebration has a static acknowledgement.

Signup, login, parent access and data-handling routes are preserved. Demo/contact actions open email at contact@lemelyig.com. FAQ answers are deterministic; contact and report illustrations do not claim delivery. Google Classroom remains labeled coming soon. No deployment, new messaging backend or application-wide component migration was performed.

## Verification

- `npm test`: 205 files, 3,688 tests passed.
- `npm run typecheck`: passed.
- `npm run lint`: zero errors; 172 warnings, including existing export warnings; all 20 native invariants passed.
- `npm run build`: passed; all 165 chunks within the bundle budget.
- Dedicated Playwright suite: **30 passed** across desktop and mobile Chromium. Coverage includes normal and reduced motion, timed hero progression, all feature scenes, offscreen pause, keyboard celebration, pinned and mobile walkthroughs, counter progression, Binny responses, carousel position, navigation, contact destinations, axe accessibility scans, and page/heading overflow at 320, 375, 390, 414, 768, 1280 and 1440px.
- Walkthrough interaction regression: **18 repeated concurrent checks passed**. Focus and layout scrolling keep the selected review mounted; deliberate wheel, touch, keyboard or outside-pointer navigation releases it.
- Fresh code review identified two visual omissions; regression coverage was added, both were corrected, and follow-up review found no remaining material issue.
- `graphify update .` refreshed the local AST graph. Existing untracked graph output remains in place. Graphify reports its existing missing optional SQL parser and community-label warnings.
- Impeccable's detector found no issues in the changed UI files. Existing unmodified legacy stylesheet warnings were not suppressed or altered.

Preview locally with `cd web && npm run dev`, then open `/landing`.
