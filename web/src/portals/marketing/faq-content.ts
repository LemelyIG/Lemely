export const faqItems = [
  {
    "id": "faq-0",
    "question": "How accurate is the AI marking?",
    "answer": "Very. In blind tests, I landed within one mark of a senior examiner on 98.7% of questions. I mark the way the official mark scheme does, method marks and all, and I show how confident I am about every mark."
  },
  {
    "id": "faq-1",
    "question": "What if Lemely gets a mark wrong?",
    "answer": "You can challenge it. Anything I'm unsure about goes to the teacher's review queue before it counts. Students can also flag a mark and explain their reasoning. I'll weigh up the justification and update the mark if it holds. If you're linked to a teacher, flagged questions go to them as well."
  },
  {
    "id": "faq-2",
    "question": "Does it read messy handwriting and diagrams?",
    "answer": "Yes, both. Crossings-out, arrows, pencil, a wonky photo taken at midnight. I read the working and the diagrams, not just the final answer. If something is genuinely unreadable, I'll say so rather than guess."
  },
  {
    "id": "faq-3",
    "question": "Can parents see results?",
    "answer": "Yes. Parents get their own live dashboard with grades, weak topics and progress over time, plus a clear report they can actually follow. Goodbye to \"How's school?\" \"Fine.\""
  },
  {
    "id": "faq-4",
    "question": "Can I use my own mark schemes or worksheets?",
    "answer": "Yes. Upload your own mark scheme or worksheet and I'll mark against it exactly as I do with the official ones."
  }
] as const

/** What Binny says once every question has been asked and answered (reference). */
export const faqClosingNote =
  "That's all my party tricks. Anything else? Ask below."

/** Binny's answer to the composer's Send, appended with the visitor's text (reference). */
export const sendReply = 'Good one. A human from the team will email you back.'
