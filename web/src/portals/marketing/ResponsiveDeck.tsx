/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { ReactNode } from 'react'
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselPrevious,
  CarouselNext,
} from '@/components/ui/carousel'

export function ResponsiveDeck({
  label,
  children,
  className = '',
}: {
  label: string
  children: ReactNode[]
  className?: string
}) {
  return (
    <Carousel
      aria-label={label}
      className={`brand-deck ${className}`}
      opts={{
        align: 'start',
        breakpoints: { '(min-width: 760px)': { active: false } },
      }}
    >
      <CarouselContent>
        {children.map((child, i) => (
          <CarouselItem key={i} aria-label={`${i + 1} of ${children.length}`}>
            {child}
          </CarouselItem>
        ))}
      </CarouselContent>
      <div className="brand-deck-controls">
        <span className="brand-label">SWIPE OR USE THE ARROWS</span>
        <CarouselPrevious />
        <CarouselNext />
      </div>
    </Carousel>
  )
}
