import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { useMutation, type UseMutationResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  LoginRequest,
  OtpRequestBody,
  OtpRequestResponse,
  OtpVerifyBody,
  SignupRequest,
  TokenResponse,
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

interface AuthContextValue {
  session: Session | null
  login: UseMutationResult<TokenResponse, Error, LoginVariables>
  signup: UseMutationResult<
    TokenResponse,
    Error,
    { email: string; password: string; displayName?: string; phone?: string }
  >
  requestOtp: UseMutationResult<OtpRequestResponse, Error, { phone: string }>
  verifyOtp: UseMutationResult<TokenResponse, Error, { phone: string; code: string }>
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
    mutationFn: ({
      email,
      password,
      displayName,
      phone,
    }: {
      email: string
      password: string
      displayName?: string
      phone?: string
    }) =>
      request<TokenResponse>("/auth/signup", {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          role: "student",
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

  const logout = () => {
    clearSession()
    setSessionState(null)
  }

  const value: AuthContextValue = { session, login, signup, requestOtp, verifyOtp, logout }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider")
  return ctx
}
