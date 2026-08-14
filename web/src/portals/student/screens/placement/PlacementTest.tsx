/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V4 */
import { useNavigate, useParams } from "react-router-dom"
import { QuizTaker } from "@/components/quiz/QuizTaker"

/*
 * S-04 · Placement test in progress. A thin route wrapper around the
 * reusable `QuizTaker` (P4.9/P5 compose the same component for practice and
 * assigned quizzes) — this file only supplies the placement-specific exit:
 * on submit, go straight to S-05's result screen for this assignment.
 */
export function PlacementTest() {
  const navigate = useNavigate()
  const { assignmentId = "" } = useParams<{ assignmentId: string }>()

  return (
    <QuizTaker
      assignmentId={assignmentId}
      onSubmitted={() => navigate(`/student/placement/result/${assignmentId}`)}
      onExit={() => navigate("/student")}
    />
  )
}
