"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Modal/drawer primitive built on Radix Dialog — real focus-trap + restore
 * behavior for free (Design System §12: "every modal/drawer traps focus
 * correctly and restores it on close"). One shared implementation for both
 * a centered modal (danger-zone confirms) and an edge drawer (tablet
 * evidence/detail overlays), differentiated only by `side`.
 */
interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  /** "center" for a confirm modal, "right" for an overlay drawer (tablet evidence rail, graph panel). */
  side?: "center" | "right";
}

export function Modal({ open, onOpenChange, title, description, children, side = "center" }: ModalProps) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-[oklch(0.1_0.006_280_/_0.6)] backdrop-blur-sm data-[state=open]:animate-cs-fade-in" />
        <RadixDialog.Content
          className={cn(
            "fixed z-50 bg-surface-2 border border-border-strong shadow-2xl focus:outline-none",
            side === "center"
              ? "left-1/2 top-1/2 w-[min(92vw,440px)] -translate-x-1/2 -translate-y-1/2 rounded-lg p-6"
              : "right-0 top-0 h-full w-[min(90vw,360px)] overflow-y-auto cs-scrollbar p-6",
          )}
        >
          <RadixDialog.Title className="font-display italic text-h1 text-text-primary">{title}</RadixDialog.Title>
          {description && (
            <RadixDialog.Description className="mt-2 text-small text-text-secondary">
              {description}
            </RadixDialog.Description>
          )}
          <div className="mt-4">{children}</div>
          <RadixDialog.Close asChild>
            <button
              className="absolute right-4 top-4 font-mono text-micro text-text-tertiary hover:text-text-primary"
              aria-label="Close"
            >
              esc
            </button>
          </RadixDialog.Close>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
