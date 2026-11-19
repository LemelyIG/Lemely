import type { WaitlistUtm } from '@/lib/waitlist-api'

const KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'] as const
const STORE = 'lemely.waitlist.utm'

/**
 * Captures `utm_*` from the landing URL on arrival and keeps it for the tab, so a visitor who
 * scrolls, opens the dialog later or navigates within the site is still tagged. The first
 * touch wins: a later page view without UTM never clears it.
 */
export function captureWaitlistUtm(search: string = window.location.search): void {
  try {
    const params = new URLSearchParams(search)
    const found: Record<string, string> = {}
    for (const key of KEYS) {
      const value = params.get(key)
      if (value) found[key] = value.slice(0, 100)
    }
    if (Object.keys(found).length && !sessionStorage.getItem(STORE)) {
      sessionStorage.setItem(STORE, JSON.stringify(found))
    }
  } catch {
    /* storage can be blocked; the tag is a nicety, never a blocker */
  }
}

export function readWaitlistUtm(): WaitlistUtm {
  try {
    const stored = JSON.parse(sessionStorage.getItem(STORE) ?? '{}') as Record<string, string>
    return {
      utmSource: stored.utm_source ?? null,
      utmMedium: stored.utm_medium ?? null,
      utmCampaign: stored.utm_campaign ?? null,
      utmContent: stored.utm_content ?? null,
      utmTerm: stored.utm_term ?? null,
    }
  } catch {
    return {}
  }
}
