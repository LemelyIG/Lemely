import { useMutation, type UseMutationResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  ParentCodeRequestBody,
  ParentCodeRequestResponse,
  ParentCodeVerifyBody,
  ParentCodeVerifyResponse,
} from "@/lib/authTypes"

/*
 * The two pre-account steps of the parent-invites signup flow (design spec
 * §4/§5): request an email code against a specific invite, then verify it for
 * a short-lived proof token. Kept out of `AuthContext.tsx` for the same
 * reason `useInvitesApi.ts`'s own module docstring gives for
 * `useInvitePreview`/`useRedeemInvite` — neither call here mints a session,
 * so neither belongs beside `applySession`'s siblings. The one call that
 * does mint a session, `POST /auth/parent/signup`, is `parentSignup` in
 * `AuthContext.tsx` instead, exactly the same split.
 */

/**
 * `POST /auth/parent/request-code`. 404 means the invite named by
 * `inviteCode` is not a live parent invite; 400 means `email` already has an
 * account; 429 is the per-email signup cooldown. `SignupParent.tsx` classifies
 * all three via `parentRequestCodeFailure` (`signupParentLogic.ts`) rather
 * than reading `err` itself.
 */
export function useRequestParentCode(): UseMutationResult<
  ParentCodeRequestResponse,
  Error,
  ParentCodeRequestBody
> {
  return useMutation({
    mutationFn: (body: ParentCodeRequestBody) =>
      request<ParentCodeRequestResponse>("/auth/parent/request-code", {
        method: "POST",
        body: JSON.stringify(body satisfies ParentCodeRequestBody),
      }),
  })
}

/**
 * `POST /auth/parent/verify-code`. 401 means the code was wrong, expired,
 * locked out, or there was no live challenge — `otpVerifyFailureMessage`
 * (`authOutcome.ts`) maps all four to a sentence, the same mapping it already
 * owns for the phone-OTP flow this one's wire text mirrors (`Email
 * verification failed: <member>`, same four members as `OTP verification
 * failed: <member>`). 404 means the invite died between the request and this
 * call.
 */
export function useVerifyParentCode(): UseMutationResult<
  ParentCodeVerifyResponse,
  Error,
  ParentCodeVerifyBody
> {
  return useMutation({
    mutationFn: (body: ParentCodeVerifyBody) =>
      request<ParentCodeVerifyResponse>("/auth/parent/verify-code", {
        method: "POST",
        body: JSON.stringify(body satisfies ParentCodeVerifyBody),
      }),
  })
}
