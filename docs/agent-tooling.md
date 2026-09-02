# Agent tooling

Project-scoped MCP servers, plugins, and skills for Claude Code. Everything here
is committed, so a fresh clone picks it up — but the MCP servers need local
credentials that are deliberately not in the repo (see Prerequisites).

## MCP servers

Declared in `.mcp.json`. Claude Code fetches them with `npx` on first use.

| Server | Package | What it does |
| --- | --- | --- |
| `gcloud` | `@google-cloud/gcloud-mcp` | Runs `gcloud` CLI commands. One tool, `run_gcloud_command`. |
| `observability` | `@google-cloud/observability-mcp` | Reads Cloud Logging, Monitoring, Trace, and Error Reporting. 13 read-only tools. |
| `cloud-run` | `@google-cloud/cloud-run-mcp` | Lists and inspects Cloud Run services, reads service logs, and deploys. 8 tools. |

Sources: [googleapis/gcloud-mcp](https://github.com/googleapis/gcloud-mcp),
[GoogleCloudPlatform/cloud-run-mcp](https://github.com/GoogleCloudPlatform/cloud-run-mcp).

### Prerequisites

- **`gcloud` CLI on PATH** — required by the `gcloud` server, which refuses to
  start without it (`ERROR: Unable to start gcloud mcp server: gcloud executable
  not found`). Install the [Google Cloud SDK](https://cloud.google.com/sdk/docs/install).
- **Application Default Credentials** — required by `observability` and
  `cloud-run`:

  ```bash
  gcloud auth login
  gcloud auth application-default login
  ```

The servers inherit whatever the active gcloud account can do. To scope them
down, authenticate as a service account via
[impersonation](https://cloud.google.com/sdk/docs/authorizing#impersonation)
rather than relying on the servers to restrict themselves.

`cloud-run`'s `deploy_*` tools and `gcloud`'s `run_gcloud_command` both mutate
real infrastructure. Staging and production deploys are meant to go through
`.github/workflows/deploy.yml` (see [`ci-cd.md`](ci-cd.md)); reach for these
tools to inspect and debug, not to bypass the pipeline.

## Plugins

Installed at project scope, so `.claude/settings.json` carries both the
marketplace registration and the enabled list. Plugin bodies are cached under
`~/.claude/plugins/` and re-fetched per machine — they are not vendored here.

| Plugin | Marketplace | Source |
| --- | --- | --- |
| `superpowers` | `superpowers-dev` | [obra/superpowers](https://github.com/obra/superpowers) |
| `design-research`, `design-systems`, `ux-strategy`, `ui-design`, `interaction-design`, `prototyping-testing`, `design-ops`, `designer-toolkit`, `visual-critique` | `designer-skills` | [Owl-Listener/designer-skills](https://github.com/Owl-Listener/designer-skills) |

`superpowers` is the development methodology this repo's `docs/superpowers/plans`
and `docs/superpowers/specs` already come from. It ships a `SessionStart` hook
that makes its skills trigger without being asked for.

The `designer-skills` marketplace also lists 25 further collections (UX program
management, design leadership, AI product design, inclusive design) that live in
separate repos and are **not** installed. Add one with:

```bash
claude plugin install <name>@designer-skills --scope project -y
```

### Token cost

These plugins put roughly **11k tokens** of skill descriptions into every
session before any skill is invoked:

| Plugin | Always-on |
| --- | --- |
| `interaction-design` | ~2,035 |
| `ui-design` | ~1,869 |
| `design-research` | ~1,120 |
| `ux-strategy` | ~1,101 |
| `design-systems` | ~1,054 |
| `design-ops` | ~846 |
| `prototyping-testing` | ~815 |
| `visual-critique` | ~742 |
| `superpowers` | ~688 |
| `designer-toolkit` | ~683 |

Check any plugin with `claude plugin details <name>`, and drop the ones a given
piece of work does not need:

```bash
claude plugin disable <name>
```

## Vendored skills

These upstreams ship plain skills rather than plugins, so they are copied into
`.claude/skills/` and committed. Update by re-copying from upstream.

| Skills | Source | Vendored at |
| --- | --- | --- |
| `composition-patterns`, `deploy-to-vercel`, `react-best-practices`, `react-native-skills`, `react-view-transitions`, `vercel-cli-with-tokens`, `vercel-optimize`, `web-design-guidelines`, `writing-guidelines` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | `063bee9` (2026-08-28) |
| `ui-refactor`, plus the `/ui-refactor`, `/fix-hierarchy`, `/fix-typography`, `/fix-layout`, `/fix-colors` commands in `.claude/commands/` | [LovroPodobnik/refactoring-ui-skill](https://github.com/LovroPodobnik/refactoring-ui-skill) | `a9e776a` (2026-01-08) |
| `ux-heuristics` | [wondelai/skills](https://github.com/wondelai/skills/tree/main/ux-heuristics) | `eade5d1` (2026-08-29) |

The copies are byte-identical to upstream. `.pre-commit-config.yaml` exempts
them from `trailing-whitespace` and `end-of-file-fixer` so they stay that way
and a re-copy on update produces a diff that is upstream's, not ours — the same
reasoning that already exempts `reports/`. First-party skills under
`.claude/skills/` are still formatted normally; a newly vendored skill has to be
added to that exclude list by hand.

Four of the Vercel skills (`deploy-to-vercel`, `vercel-cli-with-tokens`,
`vercel-optimize`, `react-native-skills`) assume a Vercel or React Native
deployment. Lemely deploys to Cloud Run and Cloudflare Workers and has no mobile
app, so those four do not apply to this codebase — they are installed because
the collection was requested as a whole. The framework-agnostic ones
(`web-design-guidelines`, `writing-guidelines`, `react-best-practices`,
`composition-patterns`, `react-view-transitions`) do apply to `web/`.
