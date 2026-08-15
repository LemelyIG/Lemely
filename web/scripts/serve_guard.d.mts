/*
 * Types for `serve_guard.mjs`, which is plain ESM because the whole
 * `scripts/` directory is — but `adaptRules.test.ts` imports it to test its
 * behaviour rather than its source text, and the test project typechecks.
 */

/**
 * Throw unless nothing is listening on `base`.
 *
 * @param base Origin to probe, e.g. `http://127.0.0.1:4319`.
 * @param port The port, used only in the error message.
 * @param label Names the caller in the error, e.g. "the adapt gate".
 */
export declare function assertPortFree(base: string, port: number, label?: string): Promise<void>
