"use client";

import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Renders as an editorial italic Newsreader field (Ask's composer, Search's query box). */
  editorial?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, editorial = false, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "w-full bg-transparent text-text-primary placeholder:text-text-tertiary focus:outline-none",
        editorial ? "font-display italic text-[15px]" : "font-sans text-[13px]",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const BoxedInput = forwardRef<HTMLInputElement, InputProps>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "w-full rounded-md border border-border-strong bg-surface-1 px-3 py-2 font-sans text-[13px] text-text-primary placeholder:text-text-tertiary focus:outline-none",
      className,
    )}
    {...props}
  />
));
BoxedInput.displayName = "BoxedInput";
