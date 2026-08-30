"use client";

import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  loading?: boolean;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-violet text-[oklch(0.12_0.01_280)] hover:bg-[var(--cs-accent-violet-hover)] border border-transparent",
  secondary: "bg-transparent text-text-primary border border-border-strong hover:bg-white/5",
  ghost: "bg-transparent text-text-secondary border border-transparent hover:text-text-primary",
  danger:
    "bg-danger/15 text-danger border border-danger/40 hover:bg-danger/25",
};

/** Primitive button with primary/secondary/ghost/danger variants (Design System §9.4). */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "secondary", size = "md", loading = false, className, disabled, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center gap-2 rounded-md font-sans font-semibold transition-colors duration-micro ease-cs disabled:cursor-not-allowed disabled:opacity-40 active:scale-[0.98]",
          size === "sm" ? "px-3 py-1.5 text-[11.5px]" : "px-[18px] py-2.5 text-[12.5px]",
          VARIANT_CLASSES[variant],
          className,
        )}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading && (
          <span
            className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
            aria-hidden="true"
          />
        )}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
