import { useEffect, useRef, useState, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { Radio, RadioGroup } from "@/components/ui/radio"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import {
  INVITE_EXPIRY_DAYS,
  PERMISSION_COPY,
  PRESET_PERMISSIONS,
  ROLES,
  ROLE_COPY,
  assistantCapChanged,
  assistantFailureMessage,
  differsFromPreset,
  effectivePermissions,
  inviteBody,
  roleBody,
  roleChanged,
  togglePermission,
} from "@/lib/assistantRoles"
import { formatBillingDate } from "@/lib/billingFormat"
import { TEAM_PERMISSIONS, type AssistantRole, type AssistantRow, type CapPeriod, type TeamPermission } from "@/lib/billingTypes"
import { useCreateAssistantInvite, useRemoveAssistant, useSetAssistantRole, useSetMemberCap } from "@/lib/hooks/useTeamApi"
import { capBody } from "@/lib/teamModel"

/* Dialogs for the assistants panel (spec §2.3). Billing, plans and seats are never a toggle. */

function Footer({ onClose, closeLabel = "Cancel", primary }: { onClose: () => void; closeLabel?: string; primary?: ReactNode }) {
  return (
    <div className="flex justify-end gap-2">
      <Button variant={primary ? "ghost" : "secondary"} onClick={onClose}>{primary ? closeLabel : "Close"}</Button>
      {primary}
    </div>
  )
}

const Failure = ({ children }: { children: ReactNode }) => (
  <p role="alert" className="m-0 text-body-sm text-error">{children}</p>
)

/** The three presets, each with what it allows. Shared by the invite and role dialogs. */
function RolePicker({ value, onChange }: { value: AssistantRole; onChange: (role: AssistantRole) => void }) {
  return (
    <RadioGroup label="Role" value={value} onValueChange={(v) => onChange(ROLES.find((r) => r === v) ?? value)}>
      {ROLES.map((r) => (
        <Radio key={r} value={r} label={ROLE_COPY[r].label} description={ROLE_COPY[r].description} />
      ))}
    </RadioGroup>
  )
}

/**
 * Copies an invite code. The code is never logged or sent anywhere: it goes from the page to the
 * clipboard. Without clipboard access the teacher is told to copy it by hand.
 */
export function CopyCodeButton({
  code,
  label = "Copy code",
  size = "md",
  ariaLabel,
}: {
  code: string
  label?: string
  size?: "sm" | "md"
  ariaLabel?: string
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle")
  const copy = () => {
    const clip = typeof navigator === "undefined" ? undefined : navigator.clipboard
    if (!clip) {
      setState("failed")
      return
    }
    clip.writeText(code).then(
      () => setState("copied"),
      () => setState("failed"),
    )
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button variant="secondary" size={size} onClick={copy} aria-label={ariaLabel}>
        {state === "copied" ? "Copied" : label}
      </Button>
      <span role="status" className={state === "failed" ? "text-body-sm text-on-surface-variant" : "sr-only"}>
        {state === "copied" ? "Code copied" : state === "failed" ? "Couldn't copy. Select the code and copy it by hand." : ""}
      </span>
    </span>
  )
}

export function RoleDialog({ open, onClose, assistant }: { open: boolean; onClose: () => void; assistant: AssistantRow }) {
  const save = useSetAssistantRole()
  const [preset, setPreset] = useState<AssistantRole>(assistant.rolePreset)
  const [selected, setSelected] = useState<TeamPermission[]>(() => effectivePermissions(assistant.rolePreset, assistant.overrides))
  const changed = roleChanged(assistant, preset, selected)
  const custom = differsFromPreset(preset, selected)
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Role for ${assistant.name}`}
      footer={
        <Footer
          onClose={onClose}
          primary={
            <Button
              variant="primary"
              loading={save.isPending}
              disabled={!changed}
              onClick={() => save.mutate({ memberId: assistant.memberId, body: roleBody(preset, selected) }, { onSuccess: onClose })}
            >
              Save role
            </Button>
          }
        />
      }
    >
      <div className="flex flex-col gap-6">
        <RolePicker
          value={preset}
          onChange={(r) => {
            setPreset(r)
            setSelected([...PRESET_PERMISSIONS[r]])
          }}
        />
        <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
          <legend className="mb-2 p-0 text-label text-on-surface">Permissions</legend>
          {TEAM_PERMISSIONS.map((p) => (
            <Switch
              key={p}
              layout="row"
              label={PERMISSION_COPY[p]}
              checked={selected.includes(p)}
              onCheckedChange={(on) => setSelected((l) => togglePermission(l, p, on))}
            />
          ))}
          {selected.length === 0 ? (
            <p className="m-0 text-body-sm text-on-surface-variant">With every permission off, this assistant can't do anything.</p>
          ) : null}
          {custom ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="m-0 text-body-sm text-on-surface-variant">Changed from the {ROLE_COPY[preset].label} preset.</p>
              <Button size="sm" variant="ghost" className="-ms-3" onClick={() => setSelected([...PRESET_PERMISSIONS[preset]])}>
                Reset to preset
              </Button>
            </div>
          ) : null}
        </fieldset>
        <p className="m-0 text-body-sm text-on-surface-variant">Billing, plans and seats always stay with you.</p>
        {save.isError ? <Failure>{assistantFailureMessage(save.error, "save this role")}</Failure> : null}
      </div>
    </Modal>
  )
}

export function AssistantCapDialog({ open, onClose, assistant }: { open: boolean; onClose: () => void; assistant: AssistantRow }) {
  const cap = useSetMemberCap()
  const [limited, setLimited] = useState(assistant.capUnits !== null)
  const [units, setUnits] = useState(String(assistant.capUnits ?? 500))
  const [period, setPeriod] = useState<CapPeriod>(assistant.capPeriod)
  const draft = capBody(limited, units, period)
  const unchanged = draft.ok && !assistantCapChanged(assistant, draft.body)
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      title={`Spending cap for ${assistant.name}`}
      footer={
        <Footer
          onClose={onClose}
          primary={
            <Button
              variant="primary"
              loading={cap.isPending}
              disabled={!draft.ok || unchanged}
              onClick={() => draft.ok && cap.mutate({ memberId: assistant.memberId, body: draft.body }, { onSuccess: onClose })}
            >
              Save cap
            </Button>
          }
        />
      }
    >
      <div className="flex flex-col gap-4">
        <p className="m-0 text-body-sm text-on-surface-variant">Their work uses your plan allowance first, then your credits.</p>
        <Checkbox label="Limit how much they can use" checked={limited} onChange={(e) => setLimited(e.target.checked)} />
        {limited ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Up to (credits)"
              type="number"
              inputMode="numeric"
              min={0}
              value={units}
              error={draft.ok ? undefined : draft.error}
              onChange={(e) => setUnits(e.target.value)}
            />
            <Select label="Counted" value={period} onChange={(e) => setPeriod(e.target.value === "total" ? "total" : "month")}>
              <option value="month">per month</option>
              <option value="total">in total</option>
            </Select>
          </div>
        ) : (
          <p className="m-0 text-body-sm text-on-surface-variant">No limit. They can use your credits until you set one or remove them.</p>
        )}
        {cap.isError ? <Failure>{assistantFailureMessage(cap.error, "save this cap")}</Failure> : null}
      </div>
    </Modal>
  )
}

export function RemoveAssistantDialog({ open, onClose, assistant }: { open: boolean; onClose: () => void; assistant: AssistantRow }) {
  const remove = useRemoveAssistant()
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      title={`Remove ${assistant.name}`}
      footer={
        <Footer
          onClose={onClose}
          closeLabel="Keep assistant"
          primary={
            <Button variant="primary" loading={remove.isPending} onClick={() => remove.mutate(assistant.memberId, { onSuccess: onClose })}>
              Remove assistant
            </Button>
          }
        />
      }
    >
      <div className="flex flex-col gap-3">
        <p className="m-0 text-body-md text-on-surface">{assistant.name} loses access to your classes straight away.</p>
        {remove.isError ? <Failure>{assistantFailureMessage(remove.error, "remove this assistant")}</Failure> : null}
      </div>
    </Modal>
  )
}

export function InviteDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const invite = useCreateAssistantInvite()
  const [role, setRole] = useState<AssistantRole>("marker")
  const [days, setDays] = useState("7")
  const draft = inviteBody(role, days)
  const created = invite.isSuccess ? invite.data : undefined
  // The button that was pressed is replaced by the code, so focus moves to the code rather than
  // falling to the page behind the dialog (where Escape would no longer reach it).
  const codeRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (created) codeRef.current?.focus()
  }, [created])
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Invite an assistant"
      footer={
        created ? (
          <Footer onClose={onClose} />
        ) : (
          <Footer
            onClose={onClose}
            primary={
              <Button variant="primary" loading={invite.isPending} disabled={!draft.ok} onClick={() => draft.ok && invite.mutate(draft.body)}>
                Create invite code
              </Button>
            }
          />
        )
      }
    >
      {created ? (
        <div className="flex flex-col gap-3">
          <div ref={codeRef} tabIndex={-1} role="status" className="flex flex-col gap-1 outline-none">
            <p className="m-0 text-body-md text-on-surface">
              Send this code to your assistant. It works once, until {formatBillingDate(created.expiresAt)}.
            </p>
            <p className="m-0 break-all text-data-lg text-on-surface select-all">{created.code}</p>
          </div>
          <CopyCodeButton code={created.code} />
          <p className="m-0 text-body-sm text-on-surface-variant">
            It stays under Pending invites until it is used or you revoke it.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <RolePicker value={role} onChange={setRole} />
          <Select label="Code works for" value={days} onChange={(e) => setDays(e.target.value)}>
            {INVITE_EXPIRY_DAYS.map((d) => (
              <option key={d} value={String(d)}>{d === 1 ? "1 day" : `${d} days`}</option>
            ))}
          </Select>
          <p className="m-0 text-body-sm text-on-surface-variant">Assistants are free. They need their own Lemely teacher account.</p>
          {invite.isError ? <Failure>{assistantFailureMessage(invite.error, "create the invite")}</Failure> : null}
        </div>
      )}
    </Modal>
  )
}
