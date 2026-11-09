/*
 * What the "working as" provider says when a choice is dropped, and what an own-account page says.
 * Apart from `actingModel.ts` because the provider ships in the portal shell's entry chunk and
 * `actingModel.ts` needs the role and permission labels (`assistantRoles.ts`), which only the lazily
 * loaded banner and switcher use.
 */

/** A membership disappeared while it was selected (the lead removed the assistant). */
export function membershipEndedNotice(leadName: string | null): string {
  return leadName
    ? `Your access to ${leadName}'s team has ended, so you're working as yourself again.`
    : "Your access to that team has ended, so you're working as yourself again."
}

/** A selected lead's team stopped being available to assistants (a school came into the picture). */
export function leadUnavailableNotice(leadName: string | null): string {
  return leadName
    ? `${leadName}'s team isn't available to you right now, so you're working as yourself.`
    : "That team isn't available to you right now, so you're working as yourself."
}

/** The stored choice could not be checked, so nothing is sent on anyone's behalf. */
export const MEMBERSHIP_UNCONFIRMED_NOTICE =
  "We couldn't confirm your access to that team, so you're working as yourself. Pick the team again to retry."

/** The line an own-account page (billing, team) shows while the caller is acting for a lead. */
export function ownAccountNote(leadName: string): string {
  return `This page is about your own account, not ${leadName}'s. Working as ${leadName} doesn't change it.`
}
