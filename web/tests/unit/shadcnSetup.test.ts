import { expect, it } from 'vitest'
import fs from 'node:fs'

it('configures shadcn for the existing Vite aliases and stylesheet', () => {
  const config = JSON.parse(fs.readFileSync('components.json', 'utf8'))
  expect(config.aliases.ui).toBe('@/components/ui')
  expect(config.aliases.utils).toBe('@/lib/utils')
  expect(config.tailwind.css).toBe('src/index.css')
  expect(fs.readFileSync(config.tailwind.css, 'utf8')).toContain('@import "tailwindcss"')
})
