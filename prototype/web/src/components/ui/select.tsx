import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { useId } from "react";
import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface SelectProps {
  label: string;
  hideLabel?: boolean;
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  className?: string;
}

/** Radix Select 기반 선택 상자. ↑/↓로 이동, Enter로 선택, Esc로 닫는다. 선택지가 2~4개면 Segmented를 쓴다. */
export function Select({ label, hideLabel, value, onValueChange, options, disabled, className }: SelectProps) {
  const labelId = useId();
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <span id={labelId} className={cn("text-sm font-medium text-text-primary", hideLabel && "sr-only")}>
        {label}
      </span>
      <SelectPrimitive.Root value={value} onValueChange={onValueChange} disabled={disabled}>
        <SelectPrimitive.Trigger
          aria-labelledby={labelId}
          className="inline-flex h-11 min-w-40 items-center justify-between gap-2 rounded-sm border border-border-control bg-surface-raised px-3 text-md text-text-primary transition-token hover:border-text-secondary disabled:cursor-not-allowed disabled:border-border-subtle disabled:bg-surface-sunken disabled:text-text-tertiary data-[state=open]:border-border-focus md:text-base"
        >
          <SelectPrimitive.Value />
          <SelectPrimitive.Icon>
            <ChevronDown className="size-4 text-text-secondary" aria-hidden="true" />
          </SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>
        <SelectPrimitive.Portal>
          <SelectPrimitive.Content
            position="popper"
            sideOffset={4}
            className="z-50 min-w-(--radix-select-trigger-width) overflow-hidden rounded-lg bg-surface-overlay shadow-overlay"
          >
            <SelectPrimitive.Viewport className="p-2">
              {options.map((option) => (
                <SelectPrimitive.Item
                  key={option.value}
                  value={option.value}
                  disabled={option.disabled}
                  className="relative flex h-11 cursor-default items-center rounded-sm pr-9 pl-3 text-base text-text-primary outline-none select-none data-disabled:text-text-tertiary data-highlighted:bg-surface-sunken data-[state=checked]:font-semibold"
                >
                  <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
                  <SelectPrimitive.ItemIndicator className="absolute right-3">
                    <Check className="size-4 text-brand-primary" aria-hidden="true" />
                  </SelectPrimitive.ItemIndicator>
                </SelectPrimitive.Item>
              ))}
            </SelectPrimitive.Viewport>
          </SelectPrimitive.Content>
        </SelectPrimitive.Portal>
      </SelectPrimitive.Root>
    </div>
  );
}
