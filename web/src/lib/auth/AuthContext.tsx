import { createContext, useContext, useState, type ReactNode } from "react"
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
import { getDeviceId, getSession, setSession, clearSession, type Session } from "./storage"

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

interface AuthContextValue {
  session: Session | null
  login: UseMutationResult<TokenResponse, Error, { email: string; password: string }>
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

  const applySession = (result: TokenResponse) => {
    const next = toSession(result)
    setSession(next)
    setSessionState(next)
  }

  const login = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      request<TokenResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          deviceId: getDeviceId(),
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
