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
    "text-[oklch(0.18_0.03_300)] border border-transparent bg-[linear-gradient(180deg,oklch(0.8_0.125_300),oklch(0.72_0.135_300))] shadow-[inset_0_1px_0_oklch(1_0_0/0.32),inset_0_0_0_1px_oklch(0.62_0.13_300/0.55)] hover:bg-[linear-gradient(180deg,oklch(0.84_0.12_300),oklch(0.76_0.135_300))]",
  secondary:
    "bg-white/[0.015] text-text-primary border border-border-strong shadow-[inset_0_1px_0_oklch(1_0_0/0.05)] hover:bg-surface-2",
  ghost: "bg-transparent text-text-secondary border border-transparent hover:text-text-primary hover:bg-surface-2",
  danger: "bg-danger text-[oklch(0.16_0.03_25)] border border-transparent hover:brightness-110",
  "danger-ghost": "bg-transparent text-danger border border-danger/45 hover:bg-danger/10",
};

/** Primitive button (Design System §9.4). Depth from lightness + inset highlight, never drop shadows. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "secondary", size = "md", loading = false, className, disabled, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[8px] font-sans font-medium transition-[background,border-color,color,transform,opacity] duration-micro ease-cs disabled:cursor-not-allowed disabled:opacity-45 enabled:active:scale-[0.975]",
          size === "sm" ? "min-h-[30px] px-[11px] text-[12px]" : "min-h-[38px] px-4 text-[13px]",
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
