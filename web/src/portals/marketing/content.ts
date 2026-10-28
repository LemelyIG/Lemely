export { faqItems } from './faq-content'
export const marketingLinks = {
  signup: '/signup',
  login: '/login',
  demo: 'mailto:contact@lemelyig.com?subject=Book%20a%20Lemely%20demo',
  contact: 'mailto:contact@lemelyig.com',
} as const

export const proofMetrics = [
  { value: '11,000+', label: 'hand-written papers marked' },
  { value: '5 hrs', label: 'of marking saved per teacher, every week' },
  { value: '+2.5 grades', label: 'average lift after 10 marked papers' },
] as const

export const teacherFeatures = [
  {
    title: 'A class set, marked instantly',
    description:
      'Upload 30 scripts at once. Marks, comments and a review queue in minutes.',
    mobileTitle: 'Instant marking',
    mobileDescription: 'A class set marked in minutes.',
    icon: 'mark',
    soon: false,
  },
  {
    title: 'Class-wide analytics',
    description:
      'See which topic cost the whole group marks, not just one student.',
    mobileTitle: 'Class analytics',
    mobileDescription: 'See which topic cost the whole group.',
    icon: 'chart',
    soon: false,
  },
  {
    title: 'A dashboard for parents',
    description:
      'Parents follow grades and weak topics live, and get a clear progress report in one tap.',
    mobileTitle: 'Parent dashboard',
    mobileDescription: 'Live grades and weak topics at home.',
    icon: 'parents',
    soon: false,
  },
  {
    title: 'Works with Google Classroom',
    description:
      'And your LMS. Assign, collect and return papers where students already are.',
    mobileTitle: 'Google Classroom',
    mobileDescription: 'Assign and return papers in one place.',
    icon: 'class',
    soon: true,
  },
] as const

export const features = [
  {
    key: 'marking',
    title: 'Method-aware marking',
    description:
      'Marks the working, not just the answer, exactly like the official mark scheme.',
  },
  {
    key: 'confidence',
    title: 'Confidence on every mark',
    description:
      'Anything unsure goes to your review queue, never silently into a grade.',
  },
  {
    key: 'predicted',
    title: 'Predicted grade',
    description:
      'A live forecast from every paper, so results day has no surprises.',
  },
  {
    key: 'clusters',
    title: 'Weak topics, clustered',
    description:
      'Lost marks group into the topics behind them, across every paper.',
  },
  {
    key: 'trends',
    title: 'Performance trends',
    description: 'Each student and the whole class, climbing paper by paper.',
  },
  {
    key: 'plan',
    title: 'Adaptive study plans',
    description: 'A week of practice built from the marks actually lost.',
  },
  {
    key: 'xp',
    title: 'XP, streaks & Binny',
    description:
      'Students earn XP for every paper. Binny keeps them coming back.',
  },
  {
    key: 'content',
    title: 'Content generation',
    description:
      'Turn any weak topic into a worksheet, with its own mark scheme, in seconds.',
  },
] as const
