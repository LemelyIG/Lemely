import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  PHONE_CHECKOUT_BODY,
  PHONE_CHECKOUT_HEADING,
  PHONE_INVALID_MESSAGE,
  PHONE_REQUIRED_MESSAGE,
  cleanPhoneInput,
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

describe("wording: the server accepts mobile numbers only, so the copy says mobile", () => {
  it("names the rule in both field errors and never says 'phone number'", () => {
    expect(PHONE_REQUIRED_MESSAGE).toBe("Enter a mobile number.")
    expect(PHONE_INVALID_MESSAGE).toBe("Enter a valid mobile number, for example 01012345678 or +201012345678.")
    for (const text of [PHONE_REQUIRED_MESSAGE, PHONE_INVALID_MESSAGE, PHONE_CHECKOUT_HEADING, PHONE_CHECKOUT_BODY]) {
      expect(text).not.toMatch(/phone number/i)
    }
  })
})

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
  it("refuses letters and numbers with too few digits", () => {
    for (const bad of ["call me", "0101abc5678", "+", "12"]) {
      expect(validatePhoneField(bad), bad).toBe(PHONE_INVALID_MESSAGE)
    }
  })
})

describe("cleanPhoneInput", () => {
  it("strips invisible formatting characters that contact apps add around a number", () => {
    // LRE/PDF embedding marks, LRM/RLM, and the isolates (U+2066-U+2069).
    expect(cleanPhoneInput("\u202a+20 101 234 5678\u202c")).toBe("+20 101 234 5678")
    expect(cleanPhoneInput("\u200e01012345678\u200f")).toBe("01012345678")
    expect(cleanPhoneInput("\u2066+201012345678\u2069")).toBe("+201012345678")
    expect(cleanPhoneInput("\u202b\u202d\u202e0101\u2067\u2068 2345678")).toBe("0101 2345678")
  })
  it("reads a full-width plus as a plus", () => {
    expect(cleanPhoneInput("\uff0b201012345678")).toBe("+201012345678")
  })
  it("trims, and leaves everything else exactly as typed", () => {
    expect(cleanPhoneInput("  (010) 1234-5678/ ")).toBe("(010) 1234-5678/")
    expect(cleanPhoneInput("٠١٠١٢٣٤٥٦٧٨")).toBe("٠١٠١٢٣٤٥٦٧٨")
  })
})

describe("the client never blocks a number the server accepts", () => {
  // The five inputs the review found the client refusing while the server stored a number.
  const accepted: [string, string][] = [
    ["LTR embedding marks around the number", "\u202a+20 101 234 5678\u202c"],
    ["a left-to-right mark in front", "\u200e01012345678"],
    ["a full-width plus", "\uff0b201012345678"],
    ["a trailing slash", "+201012345678/"],
    ["a 00 international prefix that makes 17 digits", "0043 664 1234567890"],
  ]
  it.each(accepted)("accepts %s", (_name, input) => {
    expect(validatePhoneField(input)).toBeUndefined()
  })

  it("accepts the other punctuation libphonenumber tolerates", () => {
    for (const ok of ["(+20) 101 234 5678", "+20-101-234-5678", "+20.101.234.5678", "01012345678.", "~01012345678", "‑01012345678", "+20 101 234 5678 "]) {
      expect(validatePhoneField(ok), ok).toBeUndefined()
    }
  })

  it("does not count a leading 00 toward the digit limit, or the trunk zero after +20", () => {
    expect(validatePhoneField("00201012345678")).toBeUndefined()
    expect(validatePhoneField("+2001012345678")).toBeUndefined()
  })

  it("still refuses what no number can be", () => {
    for (const bad of ["call me", "0101abc5678", "+", "/", "12", "00", "0".repeat(41), "010 1234 567;ext=5"]) {
      expect(validatePhoneField(bad), bad).toBe(PHONE_INVALID_MESSAGE)
    }
    expect(validatePhoneField("\u200e")).toBe(PHONE_REQUIRED_MESSAGE)
  })
})

describe("the +20 display follows what the server reads", () => {
  it("hides the prefix for an Arabic-digit 00 and for a plain 20 number", () => {
    expect(usesDefaultPrefix("٠٠٢٠١٠١٢٣٤٥٦٧٨")).toBe(false)
    expect(usesDefaultPrefix("201012345678")).toBe(false)
    expect(usesDefaultPrefix("۰۰۲۰۱۰۱۲۳۴۵۶۷۸")).toBe(false)
    expect(usesDefaultPrefix("\uff0b201012345678")).toBe(false)
    expect(usesDefaultPrefix("\u202a+201012345678")).toBe(false)
  })
  it("keeps the prefix while a number that starts with 20 is still being typed", () => {
    expect(usesDefaultPrefix("2010")).toBe(true)
    expect(usesDefaultPrefix("٠١٠١٢٣٤٥٦٧٨")).toBe(true)
  })
  it("drops a leading national zero typed in Arabic or Persian digits too", () => {
    expect(tidyPhoneInput("٠١٠١٢٣٤٥٦٧٨")).toBe("١٠١٢٣٤٥٦٧٨")
    expect(tidyPhoneInput("۰۱۰۱۲۳۴۵۶۷۸")).toBe("۱۰۱۲۳۴۵۶۷۸")
    expect(tidyPhoneInput("٠٠٢٠١٠١٢٣٤٥٦٧٨")).toBe("٠٠٢٠١٠١٢٣٤٥٦٧٨")
  })
  it("writes the cleaned value back: invisible marks gone, full-width plus fixed", () => {
    expect(tidyPhoneInput("\u200e01012345678")).toBe("1012345678")
    expect(tidyPhoneInput("\u202a\uff0b20 101 234 5678\u202c")).toBe("+20 101 234 5678")
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
    expect(PHONE_CHECKOUT_HEADING).toBe("Add your mobile number to continue")
    expect(PHONE_CHECKOUT_BODY).toMatch(/mobile number/)
    // Other 422s keep the generic sentence.
    expect(billingFailureMessage(new ApiError(422, "422", { code: "other" }), "start checkout")).toBe(
      "Couldn't start checkout. Check the details and try again.",
    )
  })
})
