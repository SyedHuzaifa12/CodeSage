"use client";

import * as RadixTabs from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

/**
 * Department-style tab row (Design System §16 Reports): mono labels, one
 * underline on the active tab. Radix gives real roving-tabindex keyboard
 * navigation (arrow keys between tabs) for free — genuine accessibility
 * value over a hand-rolled div row.
 */
export const Tabs = RadixTabs.Root;
export const TabsContent = RadixTabs.Content;

export function TabsList({ className, ...props }: RadixTabs.TabsListProps) {
  return (
    <RadixTabs.List
      className={cn("flex gap-6 border-b border-border-subtle", className)}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }: RadixTabs.TabsTriggerProps) {
  return (
    <RadixTabs.Trigger
      className={cn(
        "font-mono text-[11px] pb-4 -mb-px text-text-tertiary border-b-[1.5px] border-transparent transition-colors duration-standard ease-cs",
        "data-[state=active]:text-text-primary data-[state=active]:border-violet",
        "hover:text-text-secondary focus-visible:text-text-primary",
        className,
      )}
      {...props}
    />
  );
}
