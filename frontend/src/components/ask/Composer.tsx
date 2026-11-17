"use client";

import { ArrowUp, SlidersHorizontal, Square } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export const MAX_QUESTION_LENGTH = 4000;
const MAX_HEIGHT_PX = 200;

export interface ComposerHandle {
  focus: () => void;
}

/**
 * The message box. Grows with the text (up to a limit, then scrolls), Enter sends, Shift+Enter adds a line, and while
 * an answer is being produced the send button turns into Stop. Never sends mid-IME-composition (Japanese, Chinese,
 * Korean input), which is the classic way a chat box eats a user's half-typed word.
 */
export const Composer = forwardRef<
  ComposerHandle,
  {
    value: string;
    onChange: (value: string) => void;
    onSubmit: () => void;
    onStop: () => void;
    busy: boolean;
    /** True when sending must be blocked for a reason other than "empty" (e.g. no retrieval sources selected). */
    blocked?: boolean;
    placeholder?: string;
    optionsOpen: boolean;
    optionsActive: boolean;
    onToggleOptions: () => void;
    optionsPanel?: ReactNode;
  }
>(function Composer(
  { value, onChange, onSubmit, onStop, busy, blocked = false, placeholder, optionsOpen, optionsActive, onToggleOptions, optionsPanel },
  ref,
) {
  const area = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({ focus: () => area.current?.focus({ preventScroll: true }) }), []);

  const resize = useCallback(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, []);
  useEffect(resize, [value, resize]);

  const canSend = value.trim().length > 0 && !busy && !blocked;

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    if (canSend) onSubmit();
  }

  return (
    <div
      className={cn(
        "rounded-[18px] border bg-surface-1 shadow-sm transition-[border-color,box-shadow] duration-micro",
        "border-border-strong focus-within:border-[var(--cs-accent-violet)] focus-within:shadow-[0_0_0_3px_var(--cs-violet-tint)]",
      )}
    >
      {optionsOpen && optionsPanel && <div className="cs-fade-in border-b border-border-subtle px-4 py-3">{optionsPanel}</div>}
      <div className="flex items-end gap-2 p-2.5">
        <button
          type="button"
          onClick={onToggleOptions}
          aria-expanded={optionsOpen}
          aria-label="Retrieval options"
          title="Retrieval options"
          className={cn(
            "relative grid h-10 w-10 flex-none place-items-center rounded-[12px] text-text-tertiary transition-colors hover:bg-surface-2 hover:text-text-primary",
            optionsOpen && "bg-surface-2 text-text-primary",
          )}
        >
          <SlidersHorizontal size={17} strokeWidth={1.7} aria-hidden="true" />
          {optionsActive && <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-[var(--cs-accent-violet)]" aria-label="Custom options on" />}
        </button>
        <label htmlFor="ask-input" className="sr-only">
          Ask about this repository
        </label>
        <textarea
          id="ask-input"
          ref={area}
          rows={1}
          value={value}
          maxLength={MAX_QUESTION_LENGTH}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder ?? "Ask about this repository…"}
          className="max-h-[200px] min-h-[40px] flex-1 resize-none bg-transparent py-2.5 text-[15px] leading-[1.5] text-text-primary placeholder:text-text-tertiary focus:outline-none"
        />
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop generating"
            title="Stop generating"
            className="grid h-10 w-10 flex-none place-items-center rounded-full bg-text-primary text-bg transition-transform active:scale-95"
          >
            <Square size={13} fill="currentColor" aria-hidden="true" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => canSend && onSubmit()}
            disabled={!canSend}
            aria-label="Send question"
            title="Send (Enter)"
            className="grid h-10 w-10 flex-none place-items-center rounded-full bg-[var(--cs-accent-violet)] text-[var(--cs-on-accent)] shadow-sm transition-[transform,opacity,background] enabled:hover:bg-[var(--cs-accent-violet-hover)] enabled:active:scale-95 disabled:cursor-not-allowed disabled:opacity-35"
          >
            <ArrowUp size={18} strokeWidth={2.2} aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  );
});
