export interface PublicPageCopy {
  path: string
  title: string
  metaTitle?: string
  description: string
  sections: { heading: string; paragraphs: string[] }[]
}

export const publicPages: PublicPageCopy[] = [
  {
    path: '/about',
    title: 'About Us',
    metaTitle: 'Cambridge past paper marking and revision',
    description: 'Lemely marks handwritten Cambridge IGCSE, O Level and A Level past papers and helps you turn question-by-question feedback into a revision plan.',
    sections: [
      {
        heading: 'Why we built Lemely',
        paragraphs: [
          'You finish a past paper, open the mark scheme and get stuck on an answer that looks close to the one on the page. Does your explanation say enough? Would you still get a method mark if the last line is wrong? Those are hard calls to make on your own, especially when you are revising between lessons.',
          'We built Lemely to make that part of exam practice easier. It gives students a way to see where marks went on a handwritten paper and decide what to do with the result while the questions are still fresh.',
        ],
      },
      {
        heading: 'How past paper marking works',
        paragraphs: [
          'Work through a Cambridge IGCSE, O Level or A Level past paper on paper as you would in an exam. Upload your handwritten answers to Lemely and identify the paper you attempted. Lemely assesses your answers against the mark scheme and breaks the result down by question. When grade boundaries are available for that paper, you can see how your total compares with them.',
          'Open a question to see the mark, the relevant mark scheme criteria and the feedback on your answer. Where the scheme awards marks for working, the steps you wrote can earn credit. If you used the right formula and made an arithmetic slip at the end, the feedback can help you tell which step to correct and which to keep.',
          'The marks are estimates. If the feedback on a question looks off, check it against the mark scheme or take the question to a teacher. That is especially useful for answers that could be worded several ways.',
        ],
      },
      {
        heading: 'What to revise after a marked paper',
        paragraphs: [
          'Start with the questions that cost you marks. Check whether you missed a fact, chose the wrong method or left part of the question unanswered. Each of those needs a different kind of practice. For example, if you know how to do a calculation but keep leaving the unit off your answer, practise writing the result in full before moving on to harder versions of the same question.',
          'Lemely uses your results to point out weaker topics and suggest practice. You can work through questions on one topic, use flashcards to revisit material you need to recall or follow a study plan based on the areas that need more work. After a few practice sessions, try another paper and compare the results by topic. This gives you something more specific to look for than a change in your total score.',
        ],
      },
      {
        heading: 'How teachers use Lemely',
        paragraphs: [
          'A teacher can upload a class set, review the marks and see which questions caused trouble across the class. If the same part of a question comes up repeatedly, it can become the next worked example in a lesson. A student who missed a different step can get feedback on their own answer.',
          'Teachers can also use their own worksheets and mark schemes. That makes it possible to check understanding after a lesson without waiting for the next full past paper.',
        ],
      },
      {
        heading: 'What parents can see',
        paragraphs: [
          'A parent with a linked account can follow results and see topics their child is finding difficult. It gives them something concrete to talk about before the next mock, such as whether a topic has improved after practice or whether it would help to go through an answer together.',
        ],
      },
    ],
  },
  {
    path: '/terms',
    title: 'Terms & Conditions',
    description: 'The rules for using Lemely, submitting work, managing subscriptions and credits, and getting help with your account or a purchase.',
    sections: [
      {
        heading: 'When these terms apply',
        paragraphs: [
          'These terms cover your use of the Lemely website and study services, including past paper marking, practice activities and any paid plans or credits you buy. By creating an account or using the service, you agree to follow these terms. If you buy something for another user, the payment terms apply to you as the payer.',
          'The Privacy Policy explains how Lemely handles your information. The Refund Policy explains how to ask us to review a charge and what happens when we issue a refund.',
        ],
      },
      {
        heading: 'Your account',
        paragraphs: [
          'Give us accurate information when you sign up and keep your contact details up to date so you can receive account and payment notices. Keep your sign-in details private and contact us if you suspect someone has accessed your account.',
          'If you are under 18, ask your parent or legal guardian for permission before using Lemely. If you use Lemely for a class or link a parent account to a student, use the access that has been granted to you and tell us if you can see work you should not have access to.',
        ],
      },
      {
        heading: 'Papers, answers and other material you share',
        paragraphs: [
          'You keep any rights you have in the work you submit. By uploading work, you give Lemely permission to use it to provide the service. This includes reading and marking submissions, producing feedback and showing results to people who have access through your account, class or school.',
          'Only upload material you have permission to share. This applies to student scripts, worksheets and mark schemes. When you upload work on behalf of someone else, follow your school’s rules and any duties you have to that person. Leave out personal details that are unnecessary for marking.',
          'Rights in third-party exam papers and mark schemes remain with their owners. Follow any conditions those owners place on copying or sharing their materials.',
        ],
      },
      {
        heading: 'Using Lemely responsibly',
        paragraphs: [
          'Use Lemely for learning, teaching and other purposes you are authorised to carry out. Follow the rules of your school and examination centre about what help you can use during an assessment. Take responsibility for any work you submit as your own.',
          'Do not impersonate someone, access an account or class without permission, harass other users, submit unlawful material or interfere with the service. Tell us if you find content or behaviour that puts another user at risk.',
        ],
      },
      {
        heading: 'Marks, grade estimates and study advice',
        paragraphs: [
          'Lemely is independent of Cambridge. Marks, grade estimates and study recommendations are for practice and revision. An exam board or school decides official results under its own rules.',
          'Automated feedback can misread handwriting or give the wrong mark. Check the mark scheme and ask a teacher if a result matters for a school decision or if you are relying on the feedback to prepare for an exam. A study plan can help you decide where to spend time. Your final grade will depend on your exam performance and how it is assessed.',
        ],
      },
      {
        heading: 'Paid plans and renewal',
        paragraphs: [
          'When paid plans are available, check the price, included usage and billing period before confirming your purchase. The payer is responsible for reviewing the charge and for managing renewal. If you pay for another user, including a linked student, that user receives the benefits of the purchase.',
          'Subscriptions renew automatically unless the payer cancels before the next renewal. Cancellation stops future renewals. Access continues until the end of the paid period and unused plan allowance expires at that point. Cancelling a subscription does not automatically refund an earlier charge.',
        ],
      },
      {
        heading: 'Credits and automatic top-ups',
        paragraphs: [
          'You can use purchased credits for eligible activities. Where an activity draws from your plan, we use the included allowance first and then draw on your available credits. Purchased credits expire 12 months after purchase. The Refund Policy explains how credit purchases are treated when you ask us to review a charge.',
          'If you enable automatic top-ups, you authorise Lemely to charge the payment method you saved for the pack you selected when your balance reaches the top-up threshold. The monthly limit you set applies to those automatic purchases. Review the pack and limit before turning top-ups on.',
        ],
      },
      {
        heading: 'Payment problems and refunds',
        paragraphs: [
          'Contact us if a payment looks wrong or you paid for access you could not use. Include enough information to locate the charge, such as the receipt reference, date and amount. Keep full card numbers, security codes and passwords out of your message.',
          'If we issue a refund, we send it to the original payment method. The Refund Policy explains how refunds can affect a subscription or credit balance and when to contact us if you cannot see the refund.',
        ],
      },
      {
        heading: 'Service changes and restricted access',
        paragraphs: [
          'Features and subject coverage can change as the service develops. If a change affects a paid plan, any rights or remedies you have under applicable law continue to apply.',
          'We may restrict access to protect an account or another user, respond to misuse or comply with a legal requirement. If you believe an account restriction is a mistake, contact us so we can review it.',
        ],
      },
      {
        heading: 'Your rights and how to raise a concern',
        paragraphs: [
          'You keep the rights and remedies available to you under applicable consumer protection law. If you have a dispute about the service or a purchase, contact us with the account or receipt details and explain what went wrong. You can also raise a complaint with the consumer protection authority where you are entitled to do so.',
        ],
      },
    ],
  },
  {
    path: '/refund-policy',
    title: 'Refund Policy',
    description: 'How to ask about a Lemely payment and what happens if we issue a refund.',
    sections: [
      {
        heading: 'New subscriptions and renewals',
        paragraphs: [
          'Cancel before your next renewal if you want to stop future subscription charges. You can still use the plan until the current paid period ends. Cancelling alone does not refund a payment.',
          'If you believe a payment should be refunded, contact us as soon as you can, preferably within 14 days of the charge. Tell us if you were charged twice, charged the wrong amount or could not use the service you paid for. The 14 days are a guide for getting in touch. Any longer period you have by law still applies.',
          'A full refund of the current subscription period can end the plan early and remove the unused allowance for that period.',
        ],
      },
      {
        heading: 'Credits and top-ups',
        paragraphs: [
          'Purchased credits expire 12 months after purchase and generally cannot be exchanged for money. This also applies to automatic top-ups. If we issue a full refund for a credit purchase, we may remove any remaining credits from that purchase.',
          'If marking fails, it does not use your plan allowance or credits. If your balance looks wrong, send us the date and the name of the paper so we can check.',
        ],
      },
      {
        heading: 'Requesting a refund',
        paragraphs: [
          'Email us from the address used for the purchase. Include the payment date, amount, receipt reference if you have it and the reason for the request. Keep full card numbers, security codes and passwords out of the email.',
          'If we issue a refund, it goes back to the original payment method. We follow any refund deadlines that apply by law. Your bank determines when the refund appears on your statement. If you still cannot see it 10 business days after we confirm it was sent, contact us so we can help trace it.',
          'Your statutory rights apply to all purchases covered by this policy.',
        ],
      },
    ],
  },
  {
    path: '/privacy',
    title: 'Privacy Policy',
    description: 'What Lemely collects, who can see it and how to ask about your personal information.',
    sections: [
      {
        heading: 'Information we collect',
        paragraphs: [
          'When you join the waitlist, create an account or send us a message, we collect the details you provide. These can include your name, email address, role and phone number. We use them to manage access, send account and waitlist updates, and answer your questions.',
          'When you submit a paper, we use the scan and related marking materials to read your answers, assess them and keep track of your progress. We also collect sign-in and error information to protect accounts and fix problems.',
          'When payments are available and you make a purchase, we use the purchase details to provide what you paid for, send receipts and handle billing questions. Paymob handles payment details entered at checkout.',
        ],
      },
      {
        heading: 'Who can see your information',
        paragraphs: [
          'Linked parents can see results and progress for their own linked students. Class teachers and school administrators can see student work where their role gives them access. Lemely staff may access information needed to manage the service, respond to a request or look into a report.',
          'We use outside providers for services such as sign-in, email and file storage. We send uploaded scans or answer text to Google when needed to read handwriting, mark work or generate study materials.',
          'If you use tutoring, we use booking details, messages and reports to manage sessions and respond to safety concerns. Tutor profiles and approved reviews can appear in the directory. Tutors can see progress a student has shared with them through tutoring.',
        ],
      },
      {
        heading: 'How long we keep it',
        paragraphs: [
          'We keep account and study information as needed to provide access and keep your history available. We retain records when needed to respond to a dispute, investigate misuse or meet a legal obligation.',
          'You can delete eligible uploaded papers. A deleted paper stays in Recently Deleted for 30 days so you can restore it. After that, the scan and its marking results are removed. In some cases you may have to wait up to 30 days after marking before you can delete a paper.',
        ],
      },
      {
        heading: 'Your privacy choices',
        paragraphs: [
          'Email us to ask for access to your information, to correct it or to request deletion. You can also ask us to restrict a use of your information or withdraw consent where we rely on it. We may ask for enough information to confirm your identity before acting on a request.',
          'You can also raise a concern with Egypt’s Personal Data Protection Center.',
        ],
      },
    ],
  },
]
