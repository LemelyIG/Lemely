import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { useMutation, type UseMutationResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  LoginRequest,
  OtpRequestBody,
  OtpRequestResponse,
  OtpVerifyBody,
  PasswordResetConfirmBody,
  PasswordResetConfirmResponse,
  PasswordResetRequestBody,
  PasswordResetRequestResponse,
  ResendVerificationResponse,
  SignupRequest,
  TokenResponse,
  VerifyEmailBody,
  VerifyEmailResponse,
} from "@/lib/authTypes"
import {
  getDeviceId,
  getSession,
  setSession,
  clearSession,
  subscribeToSession,
  type Session,
} from "./storage"

/*
 * Session/auth plumbing shared by every portal. Each network call is a
 * react-query mutation wrapping the typed `request()` client; a successful
 * signup/login/OTP-verify mints a Session that's persisted to localStorage
 * (via lib/auth/storage) and mirrored into this context's state so consumers
 * re-render immediately. `logout()` clears both.
 *
 * No `fallback` is ever passed to `request()` here — an auth failure must
 * surface as a real ApiError, never silently resolve.
 *
 * `verifyEmail`, `resendVerification`, `requestPasswordReset` and
 * `confirmPasswordReset` (Task 13, spec §4.4's G-07/G-06) join the group
 * below without an `onSuccess: applySession` of their own: none of the four
 * returns a token, so none of them has a session to mint — that is
 * `login`/`signup`/`verifyOtp`'s shape, not this one, exactly the same
 * distinction `requestOtp` already draws against those three. Nothing here
 * clears the session on `confirmPasswordReset` either, even though
 * `AuthService.reset_password` revokes every device server-side: G-06 is one
 * of the nine routes `LoginRoute` bounces a signed-in visitor away from
 * (spec §4.4), so this mutation is never reachable with a session in this
 * context to clear in the first place.
 */

/**
 * Login variables. `confirmDeviceEviction` is the second half of the D5.12
 * handshake: the first attempt is sent without it and may come back 409 with
 * the account's signed-in devices (G-10); the same credentials are re-sent with
 * it once the user has agreed to sign the oldest device out. The password is
 * therefore verified again on confirm, which is what makes the confirmation
 * unforgeable by anyone who did not just type it.
 */
export interface LoginVariables {
  email: string
  password: string
  confirmDeviceEviction?: boolean
}

/**
 * The two roles a visitor may request for *themselves* on `/signup` (D7.1).
 * `school_admin` and `platform_admin` are privileged and are never offered on
 * this form — narrowing the type here, rather than only in what G-02 renders,
 * means no call site can even construct a signup request for either, not
 * merely that the UI declines to. The server enforces the identical allowlist
 * independently (`_SELF_SERVICE_SIGNUP_ROLES`, `lemely/web/routers/auth.py`)
 * and 403s anything else — this type is belt, that check is suspenders (D1.7,
 * revised in scope but not in spirit by D7.1: a self-registered teacher
 * escalates nothing, every teacher service being ownership-scoped by
 * construction with no super-role bypass).
 */
export type SelfServiceRole = "student" | "teacher"

/**
 * Signup variables. `role` is `SelfServiceRole`, not the wire-level `Role`
 * (`authTypes.ts`), for exactly the reason that type's own comment gives.
 *
 * `acceptedTerms` (D7.11) has no default here either, mirroring
 * `SignupRequestDTO.acceptedTerms`'s own refusal to default it: a caller
 * (G-03) must decide it explicitly, never inherit a silent `false` from this
 * type the way an optional field would let it.
 */
export interface SignupVariables {
  email: string
  password: string
  role: SelfServiceRole
  acceptedTerms: boolean
  displayName?: string
  phone?: string
}

interface AuthContextValue {
  session: Session | null
  login: UseMutationResult<TokenResponse, Error, LoginVariables>
  signup: UseMutationResult<TokenResponse, Error, SignupVariables>
  requestOtp: UseMutationResult<OtpRequestResponse, Error, { phone: string }>
  verifyOtp: UseMutationResult<TokenResponse, Error, { phone: string; code: string }>
  verifyEmail: UseMutationResult<VerifyEmailResponse, Error, { token: string }>
  resendVerification: UseMutationResult<ResendVerificationResponse, Error, void>
  requestPasswordReset: UseMutationResult<PasswordResetRequestResponse, Error, { email: string }>
  confirmPasswordReset: UseMutationResult<
    PasswordResetConfirmResponse,
    Error,
    { token: string; newPassword: string }
  >
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

function toSession(result: TokenResponse): Session {
  return {
    accessToken: result.accessToken,
    refreshToken: result.refreshToken,
    userId: result.userId,
    role: result.role,
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<Session | null>(() => getSession())

  // `lib/api.ts` also writes the stored session — it swaps in a silently
  // refreshed access token, and clears the session outright when the server
  // refuses to refresh it. Neither can reach React state on its own, so without
  // this the context would still be holding a session the storage layer had
  // already thrown away, and `RequireAuth` would keep rendering the portal.
  useEffect(() => subscribeToSession((next) => setSessionState(next)), [])

  const applySession = (result: TokenResponse) => {
    const next = toSession(result)
    setSession(next)
    setSessionState(next)
  }

  const login = useMutation({
    mutationFn: ({ email, password, confirmDeviceEviction }: LoginVariables) =>
      request<TokenResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          deviceId: getDeviceId(),
          confirmDeviceEviction: confirmDeviceEviction ?? false,
        } satisfies LoginRequest),
      }),
    onSuccess: applySession,
  })

  const signup = useMutation({
    mutationFn: ({ email, password, role, acceptedTerms, displayName, phone }: SignupVariables) =>
      request<TokenResponse>("/auth/signup", {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          role,
          acceptedTerms,
          displayName,
          phone,
          deviceId: getDeviceId(),
        } satisfies SignupRequest),
      }),
    onSuccess: applySession,
  })

  const requestOtp = useMutation({
    mutationFn: ({ phone }: { phone: string }) =>
      request<OtpRequestResponse>("/auth/otp/request", {
        method: "POST",
        body: JSON.stringify({ phone } satisfies OtpRequestBody),
      }),
  })

  const verifyOtp = useMutation({
    mutationFn: ({ phone, code }: { phone: string; code: string }) =>
      request<TokenResponse>("/auth/otp/verify", {
        method: "POST",
        body: JSON.stringify({
          phone,
          code,
          deviceId: getDeviceId(),
        } satisfies OtpVerifyBody),
      }),
    onSuccess: applySession,
  })

  const verifyEmail = useMutation({
    mutationFn: ({ token }: { token: string }) =>
      request<VerifyEmailResponse>("/auth/verify-email", {
        method: "POST",
        body: JSON.stringify({ token } satisfies VerifyEmailBody),
      }),
  })

  // Deliberately no request body — `ResendVerificationResponseDTO`'s own
  // docstring is explicit that the caller is read from the bearer token, on
  // both ends: a body-supplied address would let an attacker trigger a send
  // to someone else's inbox. That does mean this is the first *authenticated*
  // call under the `/auth/` prefix: `api.ts`'s `isAuthCall` check (anything
  // starting `/auth/`) exists to keep login/signup/refresh's own 401s from
  // ever being read as "stale token", and as a side effect it also skips this
  // path's pre-emptive refresh and its one-shot 401 retry — both harmless for
  // those public routes, which never depend on the bearer token being fresh.
  // For this route a stale access token can therefore surface as a bare 401
  // instead of transparently refreshing first, same as it would if `api.ts`
  // did not special-case `/auth/` at all. Left as is: `api.ts` is outside
  // this task's file list, and any other authenticated request the same
  // screen fires in the background still refreshes the stored session
  // normally, which this call then picks up on a retry.
  const resendVerification = useMutation({
    mutationFn: () =>
      request<ResendVerificationResponse>("/auth/verify-email/resend", { method: "POST" }),
  })

  const requestPasswordReset = useMutation({
    mutationFn: ({ email }: { email: string }) =>
      request<PasswordResetRequestResponse>("/auth/password-reset/request", {
        method: "POST",
        body: JSON.stringify({ email } satisfies PasswordResetRequestBody),
      }),
  })

  const confirmPasswordReset = useMutation({
    mutationFn: ({ token, newPassword }: { token: string; newPassword: string }) =>
      request<PasswordResetConfirmResponse>("/auth/password-reset/confirm", {
        method: "POST",
        body: JSON.stringify({ token, newPassword } satisfies PasswordResetConfirmBody),
      }),
  })

  const logout = () => {
    clearSession()
    setSessionState(null)
  }

  const value: AuthContextValue = {
    session,
    login,
    signup,
    requestOtp,
    verifyOtp,
    verifyEmail,
    resendVerification,
    requestPasswordReset,
    confirmPasswordReset,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider")
  return ctx
}
