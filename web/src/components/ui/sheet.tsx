/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import * as React from "react"
import { cn } from "@/lib/utils"
import { BottomSheetSurface } from "@/components/ui/bottom-sheet"
import { useNativeFrame } from "@/lib/useNativeFrame"
import { X as XIcon } from "@phosphor-icons/react"
import { Dialog as SheetPrimitive } from "radix-ui"

function Sheet({ ...props }: React.ComponentProps<typeof SheetPrimitive.Root>) {
  return <SheetPrimitive.Root data-slot="sheet" {...props} />
}

function SheetTrigger({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Trigger>) {
  return <SheetPrimitive.Trigger data-slot="sheet-trigger" {...props} />
}

function SheetClose({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Close>) {
  return <SheetPrimitive.Close data-slot="sheet-close" {...props} />
}

function SheetPortal({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Portal>) {
  return <SheetPrimitive.Portal data-slot="sheet-portal" {...props} />
}

function SheetOverlay({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Overlay>) {
  return (
    <SheetPrimitive.Overlay
      data-slot="sheet-overlay"
      className={cn(
        "fixed inset-0 z-scrim bg-scrim native:bg-scrim-dialog motion-reduce:animate-none data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0",
        className
      )}
      {...props}
    />
  )
}

function SheetContent({
  className,
  children,
  side = "right",
  showCloseButton = true,
  nativeHeader,
  nativeBodyClassName = "p-6",
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & {
  /** `adaptive`: a floating panel from the end edge from `sm`, a bottom sheet below it. */
  side?: "top" | "right" | "bottom" | "left" | "adaptive"
  showCloseButton?: boolean
  /** The native grabber sheet's header, inside the drag region right under the grabber (a title that
   * should sit close to it). Where the sheet is not native it renders first in the content instead. */
  nativeHeader?: React.ReactNode
  /** Classes for the native sheet's scrolling body; the default is the 24px inset. */
  nativeBodyClassName?: string
}) {
  const { native } = useNativeFrame()
  const closeRef = React.useRef<HTMLButtonElement>(null)
  if (native && (side === "bottom" || side === "adaptive")) {
    // Native frame: the grabber sheet. Radix keeps the focus trap, Escape and the label;
    // a drag past the threshold clicks the hidden Close so focus returns to the trigger.
    return (
      <SheetPortal>
        <SheetOverlay />
        <SheetPrimitive.Content asChild {...props}>
          <BottomSheetSurface
            data-slot="sheet-content"
            detents={["content"]}
            onDismiss={() => closeRef.current?.click()}
            header={nativeHeader ?? null}
            bodyClassName={nativeBodyClassName}
          >
            {children}
            <SheetPrimitive.Close ref={closeRef} tabIndex={-1} className="sr-only">
              Close
            </SheetPrimitive.Close>
          </BottomSheetSurface>
        </SheetPrimitive.Content>
      </SheetPortal>
    )
  }
  return (
    <SheetPortal>
      <SheetOverlay />
      <SheetPrimitive.Content
        data-slot="sheet-content"
        className={cn(
          "fixed z-modal flex flex-col gap-4 bg-surface shadow-panel transition ease-out-soft data-[state=closed]:animate-out data-[state=closed]:duration-300 data-[state=open]:animate-in data-[state=open]:duration-500",
          side === "right" &&
            "inset-y-0 end-0 h-full w-3/4 border-s data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right sm:max-w-sm",
          side === "left" &&
            "inset-y-0 start-0 h-full w-3/4 border-e data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left sm:max-w-sm",
          side === "top" &&
            "inset-x-0 top-0 h-auto border-b data-[state=closed]:slide-out-to-top data-[state=open]:slide-in-from-top",
          side === "bottom" &&
            "inset-x-0 bottom-0 h-auto border-t data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom",
          side === "adaptive" &&
            "inset-x-2 bottom-2 max-h-[85dvh] overflow-y-auto max-sm:data-[state=closed]:slide-out-to-bottom max-sm:data-[state=open]:slide-in-from-bottom sm:inset-x-auto sm:inset-y-2.5 sm:end-2.5 sm:max-h-none sm:w-100 sm:data-[state=closed]:slide-out-to-right sm:data-[state=open]:slide-in-from-right",
          "motion-reduce:animate-none",
          className
        )}
        {...props}
      >
        {nativeHeader}
        {children}
        {showCloseButton && (
          <SheetPrimitive.Close className="absolute top-0.5 end-0.5 grid size-11 place-items-center rounded-xs opacity-70 ring-offset-surface transition-opacity hover:opacity-100 active:opacity-100 focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-on-surface-variant">
            <XIcon className="size-4" />
            <span className="sr-only">Close</span>
          </SheetPrimitive.Close>
        )}
      </SheetPrimitive.Content>
    </SheetPortal>
  )
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-header"
      className={cn("flex flex-col gap-1.5 p-4", className)}
      {...props}
    />
  )
}

function SheetFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-footer"
      className={cn("mt-auto flex flex-col gap-2 p-4", className)}
      {...props}
    />
  )
}

function SheetTitle({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title
      data-slot="sheet-title"
      className={cn("font-semibold text-on-surface", className)}
      {...props}
    />
  )
}

function SheetDescription({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return (
    <SheetPrimitive.Description
      data-slot="sheet-description"
      className={cn("text-sm text-on-surface-variant", className)}
      {...props}
    />
  )
}

export {
  Sheet,
  SheetTrigger,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
}
