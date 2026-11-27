import { useNavigate } from "react-router-dom"
import { useCreateFromPaper } from "@/lib/hooks/usePracticeHubApi"
import type { PastPaper } from "@/lib/practiceHubTypes"
import { printFailure, runPrint, type PrintFailure } from "./papersFlow"
import type { PaperOption, PaperSheetView } from "./papersModel"

/**
 * The paper sheet's one mutation, lent as a plain `print(choice)`. Kept out of
 * the `.tsx` so the sheet reads no data itself; the decisions are `runPrint` and
 * `printFailure`. `failure` is the last attempt's, and clears when a new one starts.
 */
export function usePrintPaper(
  paper: PastPaper,
  view: PaperSheetView,
): { print: (choice: PaperOption) => Promise<unknown>; pending: boolean; failure: PrintFailure | null } {
  const navigate = useNavigate()
  const create = useCreateFromPaper()
  return {
    print: (choice) => runPrint({ mutate: (args) => create.mutateAsync(args), navigate: (to) => navigate(to) }, paper, view, choice),
    pending: create.isPending,
    failure: create.isError ? printFailure(create.error) : null,
  }
}
