import { expect, it } from 'vitest'
import { faqItems, features, marketingLinks, proofMetrics, teacherFeatures } from '@/portals/marketing/content'

it('preserves supplied proof and qualification', () => {
  expect(proofMetrics.map(x => x.value)).toEqual(['11,000+', '5 hrs', '+2.5 grades'])
  expect(teacherFeatures.find(x => x.soon)?.title).toContain('Google Classroom')
  expect(features).toHaveLength(8)
  expect(faqItems).toHaveLength(5)
})
it('connects conversion and contact actions to real destinations', () => {
  expect(marketingLinks.signup).toBe('/signup')
  expect(marketingLinks.login).toBe('/login')
  expect(marketingLinks.demo).toMatch(/^mailto:contact@lemelyig.com/)
})
