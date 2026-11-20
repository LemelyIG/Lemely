/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* Names only, never an email. Row actions carry the assistant's name in their accessible label; a revoke failure is announced beside the list it belongs to. */
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { PERMISSION_COPY, ROLE_COPY, assistantFailureMessage } from "@/lib/assistantRoles"
import { formatBillingDate } from "@/lib/billingFormat"
import type { AssistantInvite, AssistantRow, TeamView } from "@/lib/billingTypes"
import { useRevokeAssistantInvite } from "@/lib/hooks/useTeamApi"
import { assistantCapText } from "@/lib/teamModel"
import { AssistantCapDialog, CopyCodeButton, InviteDialog, RemoveAssistantDialog, RoleDialog } from "./AssistantDialogs"

/* Assistants and pending invites (spec §2.3). Free and unlimited; names only, never an email. */

type Open = { kind: "role" | "cap" | "remove"; memberId: string } | { kind: "invite" } | null

function AssistantItem({ row, onOpen }: { row: AssistantRow; onOpen: (kind: "role" | "cap" | "remove") => void }) {
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-outline-variant bg-surface-container-lowest p-4 md:flex-row md:items-start md:justify-between md:gap-6">
      <div className="flex min-w-0 flex-col gap-1">
        <span className="text-body-md font-medium text-on-surface">{row.name}</span>
        <p className="m-0 max-w-[65ch] text-body-sm text-on-surface">
          <span className="font-medium">{ROLE_COPY[row.rolePreset].label}</span>
          {" · "}
          {row.permissions.map((p) => PERMISSION_COPY[p]).join(", ") || "No permissions"}
        </p>
        <p className="m-0 text-body-sm tabular-nums text-on-surface-variant">{assistantCapText(row)}</p>
      </div>
      <div className="flex flex-none flex-wrap gap-1 md:justify-end">
        <Button variant="secondary" onClick={() => onOpen("role")} aria-label={`Edit role for ${row.name}`}>Edit role</Button>
        <Button variant="ghost" onClick={() => onOpen("cap")} aria-label={`Set cap for ${row.name}`}>Set cap</Button>
        <Button variant="ghost" onClick={() => onOpen("remove")} aria-label={`Remove ${row.name}`}>Remove</Button>
      </div>
    </li>
  )
}

function InviteItem({ invite, revoking, onRevoke }: { invite: AssistantInvite; revoking: boolean; onRevoke: () => void }) {
  return (
    <li className="flex flex-col gap-2 rounded-lg bg-surface-container-low p-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="break-all text-data-md text-on-surface">{invite.code}</span>
        <span className="text-body-sm text-on-surface-variant">
          {ROLE_COPY[invite.role].label} · works until {formatBillingDate(invite.expiresAt)}
        </span>
      </div>
      <div className="flex flex-none flex-wrap items-center gap-1">
        <CopyCodeButton code={invite.code} label="Copy" ariaLabel={`Copy ${ROLE_COPY[invite.role].label} invite code`} />
        <Button
          variant="ghost"
          loading={revoking}
          onClick={onRevoke}
          aria-label={`Revoke ${ROLE_COPY[invite.role].label} invite`}
        >
          Revoke
        </Button>
      </div>
    </li>
  )
}

export function AssistantsPanel({ team }: { team: TeamView }) {
  const revoke = useRevokeAssistantInvite()
  const [open, setOpen] = useState<Open>(null)
  const close = () => setOpen(null)
  // Held by id so a dialog always reads the current row after the team refreshes.
  const row = open && open.kind !== "invite" ? team.assistants.find((a) => a.memberId === open.memberId) : undefined
  const none = team.assistants.length === 0
  return (
    <section aria-labelledby="assistants-heading" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 id="assistants-heading" className="m-0 text-display-sm text-on-surface">Assistants</h2>
          <p className="m-0 text-body-sm text-on-surface-variant">Free and unlimited. They don't take a seat.</p>
        </div>
        <Button variant="primary" onClick={() => setOpen({ kind: "invite" })}>Invite an assistant</Button>
      </div>
      {none ? (
        <p className="m-0 max-w-[65ch] text-body-md text-on-surface-variant">
          {team.invites.length === 0
            ? "No assistants yet. Invite a colleague with their own Lemely teacher account."
            : "Nobody has joined yet. Send them the code below."}
        </p>
      ) : (
        <ul aria-label="Assistants" className="m-0 flex list-none flex-col gap-3 p-0">
          {team.assistants.map((a) => (
            <AssistantItem key={a.memberId} row={a} onOpen={(kind) => setOpen({ kind, memberId: a.memberId })} />
          ))}
        </ul>
      )}
      {team.invites.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="m-0 text-label text-on-surface">Pending invites</h3>
          <ul aria-label="Pending invites" className="m-0 flex list-none flex-col gap-2 p-0">
            {team.invites.map((inv) => (
              <InviteItem
                key={inv.inviteId}
                invite={inv}
                revoking={revoke.isPending && revoke.variables === inv.inviteId}
                onRevoke={() => revoke.mutate(inv.inviteId)}
              />
            ))}
          </ul>
          {revoke.isError ? (
            <p role="alert" className="m-0 text-body-sm text-error">{assistantFailureMessage(revoke.error, "revoke the invite")}</p>
          ) : null}
        </div>
      ) : null}
      {open?.kind === "invite" ? <InviteDialog open onClose={close} /> : null}
      {open?.kind === "role" && row ? <RoleDialog key={row.memberId} open onClose={close} assistant={row} /> : null}
      {open?.kind === "cap" && row ? <AssistantCapDialog key={row.memberId} open onClose={close} assistant={row} /> : null}
      {open?.kind === "remove" && row ? <RemoveAssistantDialog key={row.memberId} open onClose={close} assistant={row} /> : null}
    </section>
  )
}
