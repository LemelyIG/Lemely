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
}
