/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselPrevious,
  CarouselNext,
  type CarouselApi,
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
  const [api, setApi] = useState<CarouselApi>()
  const [position, setPosition] = useState(1)
  const ref = useRef<HTMLDivElement>(null)
  const buttonNavigation = useRef(false)
  useEffect(() => {
    if (!api) return
    const update = () => {
      setPosition(api.selectedScrollSnap() + 1)
      if (
        buttonNavigation.current &&
        ref.current &&
        ref.current.getBoundingClientRect().top < 80
      ) {
        window.scrollBy({
          top: ref.current.getBoundingClientRect().top - 88,
          behavior: 'instant',
        })
      }
      buttonNavigation.current = false
    }
    update()
    api.on('select', update)
    api.on('reInit', update)
    return () => {
      api.off('select', update)
      api.off('reInit', update)
    }
  }, [api])
  return (
    <Carousel
      ref={ref}
      onClickCapture={(event) => {
        buttonNavigation.current = Boolean(
          (event.target as Element).closest(
            '[data-slot=carousel-next],[data-slot=carousel-previous]',
          ),
        )
      }}
      setApi={setApi}
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
        <span className="brand-label">SWIPE OR TAP</span>
        <span role="status" aria-label="Slide position" className="brand-label">
          {position} / {children.length}
        </span>
        <CarouselPrevious />
        <CarouselNext />
      </div>
    </Carousel>
  )
}
