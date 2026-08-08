import { describe, expect, it } from "vitest"
import {
  answerCacheKey,
  answerInputKind,
  buildRetrySavePayload,
  clampQuestionIndex,
  countUnanswered,
  dirtyQuestionRefs,
  formatDuration,
  formatQuestionTopic,
  isCacheEntryUnchanged,
  isQuestionAnswered,
  mergeAnswers,
  quizAffiliationLabel,
  readCachedAnswers,
  refsToFlush,
  refsToRetry,
  remainingSeconds,
  seedAnswers,
  writeCachedAnswers,
  type CachedAnswers,
} from "@/components/quiz/quizTakerData"
import type { StudentQuizQuestion } from "@/lib/placementTypes"

function question(overrides: Partial<StudentQuizQuestion> = {}): StudentQuizQuestion {
  return {
    id: "q1",
    questionRef: "0625_s24_qp_11#5",
    position: 1,
    topic: "1 Motion, forces and energy",
    difficulty: "medium",
    questionType: "calculation",
    prompt: "Find the acceleration.",
    totalMarks: 3,
    mcqOptions: null,
    answerText: null,
    workingText: null,
    answeredAt: null,
    ...overrides,
  }
}

describe("answerInputKind — answer surface per question type", () => {
  it("routes to mcq whenever mcqOptions is non-empty, regardless of questionType", () => {
    expect(answerInputKind("recall", ["A", "B", "C"])).toBe("mcq")
  })

  it("null mcqOptions never renders mcq", () => {
    expect(answerInputKind("calculation", null)).not.toBe("mcq")
  })

  it("empty mcqOptions array never renders mcq (the inverse of the non-empty case)", () => {
    expect(answerInputKind("mcq", [])).not.toBe("mcq")
  })

  it("routes short-answer types to a single-line input", () => {
    expect(answerInputKind("calculation", null)).toBe("short")
    expect(answerInputKind("equation", null)).toBe("short")
    expect(answerInputKind("graph_read", null)).toBe("short")
    expect(answerInputKind("recall", null)).toBe("short")
  })

  it("routes structured question types to the work-it-on-paper surface", () => {
    expect(answerInputKind("explanation", null)).toBe("structured")
    expect(answerInputKind("multi_step", null)).toBe("structured")
    expect(answerInputKind("diagram", null)).toBe("structured")
    expect(answerInputKind("graph_draw", null)).toBe("structured")
  })
})

describe("isQuestionAnswered / countUnanswered — the real, current answer state", () => {
  it("a question with neither field is unanswered", () => {
    expect(isQuestionAnswered({ answerText: null, workingText: null })).toBe(false)
  })

  it("a non-empty answerText counts as answered", () => {
    expect(isQuestionAnswered({ answerText: "42", workingText: null })).toBe(true)
  })

  it("a non-empty workingText alone counts as answered (working without a final answer is still effort)", () => {
    expect(isQuestionAnswered({ answerText: null, workingText: "F = ma, so a = F/m" })).toBe(true)
  })

  it("whitespace-only text does not count as an answer", () => {
    expect(isQuestionAnswered({ answerText: "   ", workingText: "\n" })).toBe(false)
  })

  it("countUnanswered reflects live per-question state, not a stale snapshot", () => {
    const qs = [
      { answerText: "42", workingText: null },
      { answerText: null, workingText: null },
      { answerText: "", workingText: "some working" },
    ]
    expect(countUnanswered(qs)).toBe(1)
  })

  it("inverse: a fully-answered set counts zero unanswered", () => {
    const qs = [
      { answerText: "42", workingText: null },
      { answerText: null, workingText: "shown working" },
    ]
    expect(countUnanswered(qs)).toBe(0)
  })
})

describe("isCacheEntryUnchanged — a stale save must not stamp a newer answer 'saved'", () => {
  const sent = { answerText: "42", workingText: null }

  it("commits when the cache still holds exactly what this save sent", () => {
    expect(isCacheEntryUnchanged({ answerText: "42", workingText: null, dirty: true }, sent)).toBe(
      true,
    )
  })

  it("refuses to commit when the student edited the answer mid-flight", () => {
    // The load-bearing case. Without this, the completing save writes its own
    // older value back over the newer one and marks it clean, so the next
    // reload defers to the server and the newer answer is gone — while it was
    // on screen the whole time.
    expect(isCacheEntryUnchanged({ answerText: "43", workingText: null, dirty: true }, sent)).toBe(
      false,
    )
  })

  it("refuses to commit when only the OTHER field changed mid-flight", () => {
    // Both fields go on the wire together, so a working-out edit makes an
    // answerText-triggered save just as stale.
    expect(
      isCacheEntryUnchanged({ answerText: "42", workingText: "F = ma", dirty: true }, sent),
    ).toBe(false)
  })

  it("compares by value, not identity — a typed-then-undone edit still commits", () => {
    // A fresh object with equal values: identity comparison would force a
    // pointless resend and leave the entry dirty, blocking submit.
    expect(isCacheEntryUnchanged({ ...sent, dirty: true }, sent)).toBe(true)
  })

  it("treats null and empty string as different (clearing an answer is an edit)", () => {
    expect(
      isCacheEntryUnchanged({ answerText: "", workingText: null, dirty: true }, sent),
    ).toBe(false)
  })

  it("does not commit against a cache entry that no longer exists", () => {
    expect(isCacheEntryUnchanged(undefined, sent)).toBe(false)
  })
})

describe("refsToFlush — what a submit must wait on", () => {
  const cached = {
    q1: { answerText: "a", workingText: null, dirty: true },
    q2: { answerText: "b", workingText: null, dirty: false },
  }

  it("includes every dirty ref", () => {
    expect(refsToFlush(cached, new Set())).toEqual(["q1"])
  })

  it("also waits on a ref whose save is already on the wire, though it is clean", () => {
    // q2 is not dirty, but a save for it is in flight and may still FAIL.
    // Submitting without waiting would mark the paper while that answer is
    // still unconfirmed — the D3.21 shape.
    expect(refsToFlush(cached, new Set(["q2"])).sort()).toEqual(["q1", "q2"])
  })

  it("counts a ref that is both dirty and busy exactly once", () => {
    expect(refsToFlush(cached, new Set(["q1"]))).toEqual(["q1"])
  })

  it("waits on a busy ref with no cache entry at all", () => {
    expect(refsToFlush(cached, new Set(["q9"])).sort()).toEqual(["q1", "q9"])
  })

  it("is empty when nothing is dirty and nothing is on the wire", () => {
    expect(refsToFlush({ q2: cached.q2 }, new Set())).toEqual([])
    expect(refsToFlush(null, new Set())).toEqual([])
  })
})

describe("formatDuration", () => {
  it("formats under a minute as 0:ss", () => {
    expect(formatDuration(45)).toBe("0:45")
  })

  it("formats minutes and seconds", () => {
    expect(formatDuration(125)).toBe("2:05")
  })

  it("formats past an hour as h:mm:ss", () => {
    expect(formatDuration(3661)).toBe("1:01:01")
  })

  it("clamps a negative duration to 0:00 rather than showing negative time", () => {
    expect(formatDuration(-5)).toBe("0:00")
  })
})

describe("remainingSeconds — placement never gets an invented countdown", () => {
  it("returns null when the quiz has no time limit (every placement test)", () => {
    expect(remainingSeconds(null, 300)).toBeNull()
  })

  it("computes remaining seconds when a time limit exists", () => {
    expect(remainingSeconds(15, 60)).toBe(15 * 60 - 60)
  })

  it("clamps at 0 once the limit has passed, never negative", () => {
    expect(remainingSeconds(1, 120)).toBe(0)
  })
})

describe("clampQuestionIndex", () => {
  it("clamps forward past the last question", () => {
    expect(clampQuestionIndex(10, 5)).toBe(4)
  })

  it("clamps backward past the first question", () => {
    expect(clampQuestionIndex(-2, 5)).toBe(0)
  })

  it("clamps to 0 for an empty question set", () => {
    expect(clampQuestionIndex(3, 0)).toBe(0)
  })
})

describe("seedAnswers — resume after leaving (UI spec S-04)", () => {
  it("seeds local state from the server's stored answerText/workingText", () => {
    const questions = [
      question({ questionRef: "a", answerText: "42", workingText: "F=ma" }),
      question({ questionRef: "b", answerText: null, workingText: null }),
    ]
    expect(seedAnswers(questions)).toEqual({
      a: { answerText: "42", workingText: "F=ma" },
      b: { answerText: null, workingText: null },
    })
  })

  it("a question the student never touched seeds as null, not a fabricated empty string", () => {
    const [seeded] = Object.values(seedAnswers([question({ questionRef: "x" })]))
    expect(seeded.answerText).toBeNull()
    expect(seeded.workingText).toBeNull()
  })
})

describe("quizAffiliationLabel — className/teacherName rendered only when present", () => {
  it("null className and null teacherName (every placement test, D4.6 §3) yields null, never a placeholder", () => {
    expect(quizAffiliationLabel(null, null)).toBeNull()
  })

  it("inverse: a teacher-assigned quiz with both present joins them", () => {
    expect(quizAffiliationLabel("11A Physics", "Ms. Ahmed")).toBe("11A Physics · Ms. Ahmed")
  })

  it("only className present renders just that", () => {
    expect(quizAffiliationLabel("11A Physics", null)).toBe("11A Physics")
  })

  it("only teacherName present renders just that", () => {
    expect(quizAffiliationLabel(null, "Ms. Ahmed")).toBe("Ms. Ahmed")
  })

  it("whitespace-only strings are treated as absent, same rule as isQuestionAnswered", () => {
    expect(quizAffiliationLabel("  ", "\n")).toBeNull()
  })
})

describe("formatQuestionTopic — topic: null is unknown, never the empty string", () => {
  it("null renders the honest fallback", () => {
    expect(formatQuestionTopic(null)).toBe("Topic not classified")
  })

  it("inverse: a real topic passes through verbatim", () => {
    expect(formatQuestionTopic("1 Motion, forces and energy")).toBe("1 Motion, forces and energy")
  })
})

// ── A minimal in-memory `Pick<Storage, "getItem" | "setItem">` — no jsdom,
// no real `localStorage` (D3.20's node-environment rule) — plus variants
// that fail the way real storage can (throwing, corrupt JSON), so the pure
// cache functions can be pinned against both. ────────────────────────────

function fakeStorage(initial: Record<string, string> = {}) {
  const store = { ...initial }
  return {
    getItem: (key: string) => (key in store ? store[key] : null),
    setItem: (key: string, value: string) => {
      store[key] = value
    },
    _store: store,
  }
}

function throwingStorage() {
  return {
    getItem: () => {
      throw new Error("storage unavailable")
    },
    setItem: () => {
      throw new Error("storage unavailable")
    },
  }
}

describe("answerCacheKey", () => {
  it("is keyed per assignment", () => {
    expect(answerCacheKey("abc")).not.toBe(answerCacheKey("def"))
  })
})

describe("readCachedAnswers / writeCachedAnswers", () => {
  it("round-trips what was written", () => {
    const storage = fakeStorage()
    const key = answerCacheKey("a1")
    const cache: CachedAnswers = { q1: { answerText: "42", workingText: null, dirty: true } }
    writeCachedAnswers(storage, key, cache)
    expect(readCachedAnswers(storage, key)).toEqual(cache)
  })

  it("nothing cached (getItem returns null) reads as null, not an empty object", () => {
    expect(readCachedAnswers(fakeStorage(), answerCacheKey("a1"))).toBeNull()
  })

  it("corrupt/unparseable cached JSON degrades to null rather than throwing", () => {
    const storage = fakeStorage({ [answerCacheKey("a1")]: "{not json" })
    expect(() => readCachedAnswers(storage, answerCacheKey("a1"))).not.toThrow()
    expect(readCachedAnswers(storage, answerCacheKey("a1"))).toBeNull()
  })

  it("a storage that throws on read degrades to null rather than crashing the take screen", () => {
    expect(readCachedAnswers(throwingStorage(), answerCacheKey("a1"))).toBeNull()
  })

  it("a storage that throws on write is a silent best-effort no-op, not a crash", () => {
    expect(() => writeCachedAnswers(throwingStorage(), answerCacheKey("a1"), {})).not.toThrow()
  })
})

describe("mergeAnswers — a failed-to-save local edit must survive a reload", () => {
  const server = {
    q1: { answerText: "server-value", workingText: null },
    q2: { answerText: null, workingText: null },
  }

  it("no cache at all falls back to the server values verbatim (== seedAnswers's own output)", () => {
    expect(mergeAnswers(server, null)).toEqual(server)
  })

  it("a dirty cached entry (unsaved local edit) wins over the server's older value", () => {
    const cached: CachedAnswers = {
      q1: { answerText: "local-edit-never-saved", workingText: null, dirty: true },
    }
    const merged = mergeAnswers(server, cached)
    expect(merged.q1.answerText).toBe("local-edit-never-saved")
  })

  it("inverse: a clean (dirty: false) cached entry defers to the server's value, not the stale local copy", () => {
    const cached: CachedAnswers = {
      q1: { answerText: "already-synced-old-copy", workingText: null, dirty: false },
    }
    const merged = mergeAnswers(server, cached)
    expect(merged.q1.answerText).toBe("server-value")
  })

  it("a question with no cache entry at all is untouched by the merge", () => {
    const cached: CachedAnswers = {
      q1: { answerText: "edited", workingText: null, dirty: true },
    }
    const merged = mergeAnswers(server, cached)
    expect(merged.q2).toEqual(server.q2)
  })
})

describe("dirtyQuestionRefs — the retry-on-reconnect decision", () => {
  it("returns only refs still marked dirty", () => {
    const cached: CachedAnswers = {
      q1: { answerText: "a", workingText: null, dirty: true },
      q2: { answerText: "b", workingText: null, dirty: false },
      q3: { answerText: "c", workingText: null, dirty: true },
    }
    expect(dirtyQuestionRefs(cached).sort()).toEqual(["q1", "q3"])
  })

  it("inverse: no dirty entries yields an empty list — nothing to retry", () => {
    const cached: CachedAnswers = { q1: { answerText: "a", workingText: null, dirty: false } }
    expect(dirtyQuestionRefs(cached)).toEqual([])
  })

  it("no cache at all yields an empty list, not a crash", () => {
    expect(dirtyQuestionRefs(null)).toEqual([])
  })
})

describe("buildRetrySavePayload — resend both fields, the cache's known-true state", () => {
  it("carries both answerText and workingText explicitly", () => {
    const payload = buildRetrySavePayload({ answerText: "42", workingText: "F=ma" })
    expect(payload).toEqual({ answerText: "42", workingText: "F=ma" })
  })

  it("a field genuinely never touched (still null) is resent as null, not omitted", () => {
    const payload = buildRetrySavePayload({ answerText: "42", workingText: null })
    expect(payload).toEqual({ answerText: "42", workingText: null })
  })
})

describe("refsToRetry — resend the stranded, never duplicate the in-flight", () => {
  const cached = {
    q1: { answerText: "a", workingText: null, dirty: true },
    q2: { answerText: "b", workingText: null, dirty: true },
    q3: { answerText: "c", workingText: null, dirty: false },
  }

  it("returns dirty refs that are not already being saved", () => {
    expect(refsToRetry(cached, new Set(["q2"]))).toEqual(["q1"])
  })

  it("inverse: with nothing in flight, every dirty ref is retried", () => {
    expect(refsToRetry(cached, new Set())).toEqual(["q1", "q2"])
  })

  it("a clean ref is never retried even when nothing is in flight", () => {
    expect(refsToRetry(cached, new Set())).not.toContain("q3")
  })

  it("every dirty ref in flight yields nothing to retry — no duplicate PUT", () => {
    expect(refsToRetry(cached, new Set(["q1", "q2"]))).toEqual([])
  })

  it("no cache at all yields an empty list, not a crash", () => {
    expect(refsToRetry(null, new Set(["q1"]))).toEqual([])
  })
})
