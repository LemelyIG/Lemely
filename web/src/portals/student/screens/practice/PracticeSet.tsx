import { useNavigate, useParams } from "react-router-dom"
import { QuizTaker } from "@/components/quiz/QuizTaker"

/*
 * S-21 · Practice set working view. A thin route wrapper around the
 * reusable `QuizTaker` — identical shape to `PlacementTest.tsx`, the proof
 * this composition seam needs no change for a second caller. This file only
 * supplies the practice-specific exit: on submit, go to S-21's finish
 * summary for this assignment.
 */
export function PracticeSet() {
  const navigate = useNavigate()
  const { assignmentId = "" } = useParams<{ assignmentId: string }>()

  return (
    <QuizTaker
      assignmentId={assignmentId}
      onSubmitted={() => navigate(`/student/practice/result/${assignmentId}`)}
      onExit={() => navigate("/student")}
    />
  )
}
