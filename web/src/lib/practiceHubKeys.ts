/* Query keys and request paths for the Practice tab. Pure, so Vitest can pin them. */

export const RUNS_LIMIT = 10

export const practiceHubKeys = {
  runsAll: ["practice", "runs"] as const,
  runs: (limit: number) => ["practice", "runs", limit] as const,
  papers: (subjectCode: string) => ["practice", "papers", subjectCode] as const,
  /** Identical to `usePracticeTopics`'s key (usePracticeApi.ts). */
  topics: (subjectCode: string) => ["practice", "topics", subjectCode] as const,
}

export const practiceHubPaths = {
  runs: (limit: number) => `/student/practice/runs?limit=${limit}`,
  papers: (subjectCode: string) => `/student/practice/papers/${encodeURIComponent(subjectCode)}`,
  createFromPaper: (paperId: string) => `/student/practice/papers/${encodeURIComponent(paperId)}`,
  topics: (subjectCode: string) => `/student/practice/${encodeURIComponent(subjectCode)}/topics`,
}
