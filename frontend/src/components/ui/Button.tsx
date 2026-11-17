"use client";

import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "danger-ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  loading?: boolean;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--cs-accent-violet)] text-[var(--cs-on-accent)] border border-transparent shadow-sm hover:bg-[var(--cs-accent-violet-hover)]",
  secondary: "bg-surface-1 text-text-primary border border-border-strong shadow-sm hover:bg-surface-2",
  ghost: "bg-transparent text-text-secondary border border-transparent hover:text-text-primary hover:bg-surface-2",
  danger: "bg-danger text-white border border-transparent hover:brightness-110",
  "danger-ghost": "bg-transparent text-danger border border-danger/45 hover:bg-danger/10",
};

/** Primitive button (Design System §9.4): solid accent for the primary action, outlined for the rest. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "secondary", size = "md", loading = false, className, disabled, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[8px] font-sans font-medium transition-[background,border-color,color,transform,opacity] duration-micro ease-cs disabled:cursor-not-allowed disabled:opacity-45 enabled:active:scale-[0.975]",
          size === "sm" ? "min-h-[30px] px-[11px] text-[12.5px]" : "min-h-[38px] px-4 text-[13.5px]",
          VARIANT_CLASSES[variant],
          className,
        )}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading && (
          <span
            className="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-r-transparent"
            aria-hidden="true"
          />
        )}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
