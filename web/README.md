# Lemely Web UI

Production web UI for Lemely — a role-based single-page app with a **Teacher**
portal (grading console) and a **Student** portal (results + study). Built to
match the Claude Design mocks in `../design/project/`.

## Stack

- **Vite + React 19 + TypeScript** (strict)
- **Tailwind CSS v4** via `@tailwindcss/vite`, tokens in `src/index.css`
- **shadcn-style owned primitives** in `src/components/ui`
- **React Router** (`src/App.tsx`) + **TanStack Query** (`src/main.tsx`)
- Fonts: Instrument Serif (display) · Work Sans (body) · JetBrains Mono (data)
- Icons: `@phosphor-icons/react`

## Run

```bash
cd web
npm install
npm run dev        # http://localhost:5173  -> redirects to /teacher
```

`/` redirects to `/teacher`. The student portal is at `/student`. Each portal
sets `data-portal` on its layout root so the token layer swaps accent + neutral
hue (teacher = amber, student = terracotta).

## Scripts

| Command | What |
|---|---|
| `npm run dev` | Dev server (HMR) |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run lint` | `oxlint` |
| `npm run build` | `tsc -b && vite build` |

## Structure

```
src/
  App.tsx              router (composes both portal routes)
  main.tsx             providers (QueryClient + Router)
  index.css            Tailwind + design tokens (per-portal, data-portal scoped)
  lib/                 utils (cn), types (domain), api (typed client + SSE reader)
  components/ui/       button, card, chip, primitives (Eyebrow/Display/Meter)
  portals/
    teacher/           amber portal: layout + screens + stub data
    student/           terracotta portal: layout + screens + stub data
```

## API status

Frontend-first: screens render from local `data.ts` stubs. `src/lib/api.ts`
targets the planned FastAPI backend (proxied at `/api` by Vite) with a stub
fallback and an SSE reader (`streamActivity`) for the live-activity job streams.
When the backend lands, wire the stubs to `request()` / `streamActivity()`; the
call sites stay the same.
