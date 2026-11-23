import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { PublicPage } from '../../src/portals/marketing/PublicPage'
import { publicPages } from '../../src/portals/marketing/publicPages'

describe('public policy pages', () => {
  it('renders the revision date on each policy and omits it from About', () => {
    for (const page of publicPages) {
      const markup = renderToStaticMarkup(createElement(MemoryRouter, null, createElement(PublicPage, { page })))
      if (page.path === '/about') {
        expect(markup).not.toContain('<time')
      } else {
        expect(markup).toContain('<time dateTime="2026-11-19">19 November 2026</time>')
      }
    }
  })

  it('describes access within its boundary and keeps school administrators out of the copy', () => {
    const privacy = publicPages.find((page) => page.path === '/privacy')!
    const copy = privacy.sections.flatMap((section) => section.paragraphs).join(' ')
    expect(copy).toContain('Administrators with the appropriate access can see student work in the classes they manage and papers uploaded by teachers they oversee.')
    expect(copy).toContain('Linked parents can see results and progress for their own linked students.')
    expect(copy).not.toMatch(/school administrator/i)
  })
})
