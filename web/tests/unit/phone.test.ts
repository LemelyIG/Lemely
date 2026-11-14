import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  PHONE_CHECKOUT_HEADING,
  PHONE_INVALID_MESSAGE,
  PHONE_REQUIRED_MESSAGE,
  isCheckoutPhoneRequired,
  phoneErrorCode,
  phoneErrorMessage,
  tidyPhoneInput,
  usesDefaultPrefix,
  validatePhoneField,
} from "@/lib/phone"
import { billingFailureMessage } from "@/lib/billingOutcome"

/*
 * UD-11, client side. The server validates (libphonenumber, region EG); these pin the three small
 * jobs the client does: when the "+20" default shows, what it refuses before a round trip, and
 * how the server's two stable codes come back as sentences.
 */

const phone422 = (code: string) =>
  new ApiError(422, "422 Unprocessable", { code, message: "server wording, never shown" })

describe("usesDefaultPrefix", () => {
  it("is on for an empty field and for a national number", () => {
    expect(usesDefaultPrefix("")).toBe(true)
    expect(usesDefaultPrefix("01012345678")).toBe(true)
    expect(usesDefaultPrefix("1012345678")).toBe(true)
  })
  it("is off once the person types their own country code", () => {
    expect(usesDefaultPrefix("+44 7700 900123")).toBe(false)
    expect(usesDefaultPrefix("  +201012345678")).toBe(false)
    expect(usesDefaultPrefix("0044 7700 900123")).toBe(false)
  })
})

describe("tidyPhoneInput", () => {
  it("drops one leading national zero so the +20 in front does not read as two zeros", () => {
    expect(tidyPhoneInput("01012345678")).toBe("1012345678")
    expect(tidyPhoneInput("  01012345678  ")).toBe("1012345678")
  })
  it("leaves international input alone", () => {
    expect(tidyPhoneInput("+201012345678")).toBe("+201012345678")
    expect(tidyPhoneInput("0044 7700 900123")).toBe("0044 7700 900123")
    expect(tidyPhoneInput("1012345678")).toBe("1012345678")
  })
})

describe("validatePhoneField", () => {
  it("asks for a number when the field is empty or only spaces", () => {
    expect(validatePhoneField("")).toBe(PHONE_REQUIRED_MESSAGE)
    expect(validatePhoneField("   ")).toBe(PHONE_REQUIRED_MESSAGE)
  })
  it("accepts an Egyptian number in the ways people write it", () => {
    for (const ok of ["01012345678", "1012345678", "+201012345678", "+20 101 234 5678", "(010) 1234-5678", "201012345678"]) {
      expect(validatePhoneField(ok), ok).toBeUndefined()
    }
  })
  it("accepts an international number", () => {
    expect(validatePhoneField("+44 7700 900123")).toBeUndefined()
    expect(validatePhoneField("00971501234567")).toBeUndefined()
  })
  it("accepts Arabic-Indic digits, which the server reads as ASCII", () => {
    expect(validatePhoneField("٠١٠١٢٣٤٥٦٧٨")).toBeUndefined()
  })
  it("refuses letters, a stray plus, and numbers that are too short or too long", () => {
    for (const bad of ["call me", "0101abc5678", "+", "12", "123456", "1234567890123456", "010+1234567"]) {
      expect(validatePhoneField(bad), bad).toBe(PHONE_INVALID_MESSAGE)
    }
  })
})

describe("phoneErrorCode", () => {
  it("reads the two stable codes from a 422 object detail", () => {
    expect(phoneErrorCode(phone422("phone_required"))).toBe("phone_required")
    expect(phoneErrorCode(phone422("phone_invalid"))).toBe("phone_invalid")
  })
  it("ignores everything else, including FastAPI's own list-shaped 422", () => {
    expect(phoneErrorCode(phone422("something_else"))).toBeNull()
    expect(phoneErrorCode(new ApiError(422, "422", [{ loc: ["body", "phone"], msg: "field required" }]))).toBeNull()
    expect(phoneErrorCode(new ApiError(422, "422", "a string detail"))).toBeNull()
    expect(phoneErrorCode(new ApiError(400, "400", { code: "phone_invalid" }))).toBeNull()
    expect(phoneErrorCode(new Error("boom"))).toBeNull()
    expect(phoneErrorCode(null)).toBeNull()
  })
  it("never echoes the server's wording, only its own sentence for the code", () => {
    expect(phoneErrorMessage("phone_required")).toBe(PHONE_REQUIRED_MESSAGE)
    expect(phoneErrorMessage("phone_invalid")).toBe(PHONE_INVALID_MESSAGE)
  })
})

describe("checkout 422 phone_required", () => {
  it("is recognised as a checkout refusal", () => {
    expect(isCheckoutPhoneRequired(phone422("phone_required"))).toBe(true)
    expect(isCheckoutPhoneRequired(phone422("phone_invalid"))).toBe(false)
    expect(isCheckoutPhoneRequired(new ApiError(409, "409", { code: "phone_required" }))).toBe(false)
  })
  it("reads as the fix, not as 'check the details', anywhere billingFailureMessage is used", () => {
    expect(billingFailureMessage(phone422("phone_required"), "start checkout")).toBe(`${PHONE_CHECKOUT_HEADING}.`)
    // Other 422s keep the generic sentence.
    expect(billingFailureMessage(new ApiError(422, "422", { code: "other" }), "start checkout")).toBe(
      "Couldn't start checkout. Check the details and try again.",
    )
  })
})
