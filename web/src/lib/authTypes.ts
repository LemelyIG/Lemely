/*
 * TS interfaces mirroring lemely/web/schemas_auth.py field-for-field
 * (camelCase). Keep these in lockstep with the backend DTOs — see that module
 * for the authoritative field docs.
 */

export type Role = "student" | "parent" | "teacher" | "school_admin" | "platform_admin"

export interface SignupRequest {
  email: string
  password: string
  role: Role
  displayName?: string | null
  phone?: string | null
  deviceId?: string | null
}

export interface LoginRequest {
  email: string
  password: string
  deviceId?: string | null
  /** Agreed to sign the oldest device out (the second half of D5.12's 409 handshake). */
  confirmDeviceEviction?: boolean
}

export interface OtpRequestBody {
  phone: string
}

export interface OtpVerifyBody {
  phone: string
  code: string
  deviceId?: string | null
}

export interface TokenResponse {
  accessToken: string
  userId: string
  role: Role
  refreshToken: string | null
}

export interface OtpRequestResponse {
  status: "sent"
  /**
   * §G-05's developer affordance (D3.16). Non-null **only** when the configured
   * SMS provider does not deliver out of band (the offline mock) — with a real
   * gateway the backend always sends null. Render it in an explicitly-labelled
   * developer panel, never as ordinary product copy.
   */
  devCode: string | null
}
