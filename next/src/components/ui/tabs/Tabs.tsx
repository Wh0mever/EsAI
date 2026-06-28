"use client";

import React, { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import clsx from "clsx";

type Orientation = "horizontal" | "vertical";
type Variant = "underline" | "soft" | "solid" | "ghost";
type Size = "sm" | "md" | "lg";

type TabsContextValue = {
  value: string;
  setValue: (v: string) => void;
  orientation: Orientation;
  variant: Variant;
  size: Size;
  keepAlive: boolean;
  baseId: string;
  register: (v: string, ref: HTMLButtonElement | null, disabled: boolean) => void;
  getRefByValue: (v: string) => HTMLButtonElement | null;
  getEnabledValues: () => string[];
};

const TabsCtx = createContext<TabsContextValue | null>(null);

export type TabsRootProps = {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  orientation?: Orientation;
  variant?: Variant;
  size?: Size;
  keepAlive?: boolean;
  className?: string;
  children: React.ReactNode;
};

export function TabsRoot({
  value,
  defaultValue,
  onValueChange,
  orientation = "horizontal",
  variant = "underline",
  size = "md",
  keepAlive = false,
  className,
  children,
}: TabsRootProps) {
  const isControlled = value !== undefined;
  const [uncontrolledValue, setUncontrolledValue] = useState<string>(defaultValue || "");
  const currentValue = isControlled ? (value as string) : uncontrolledValue;
  const baseId = useId();
  const registry = useRef(new Map<string, { ref: HTMLButtonElement | null; disabled: boolean }>());

  const setValue = useCallback(
    (v: string) => {
      if (isControlled) onValueChange && onValueChange(v);
      else setUncontrolledValue(v);
    },
    [isControlled, onValueChange]
  );

  const register = useCallback((v: string, ref: HTMLButtonElement | null, disabled: boolean) => {
    registry.current.set(v, { ref, disabled });
  }, []);

  const getRefByValue = useCallback((v: string) => {
    const item = registry.current.get(v);
    return item ? item.ref : null;
  }, []);

  const getEnabledValues = useCallback(() => {
    const values: string[] = [];
    registry.current.forEach((item, key) => {
      if (!item.disabled) values.push(key);
    });
    return values;
  }, []);

  useEffect(() => {
    if (!currentValue) {
      const first = getEnabledValues()[0];
      if (first) setValue(first);
    }
  }, [currentValue, getEnabledValues, setValue]);

  const ctx = useMemo<TabsContextValue>(
    () => ({ value: currentValue, setValue, orientation, variant, size, keepAlive, baseId, register, getRefByValue, getEnabledValues }),
    [currentValue, setValue, orientation, variant, size, keepAlive, baseId, register, getRefByValue, getEnabledValues]
  );

  return (
    <TabsCtx.Provider value={ctx}>
      <div className={clsx("w-full", className)}>{children}</div>
    </TabsCtx.Provider>
  );
}

export type TabsListProps = {
  children: React.ReactNode;
  className?: string;
};

export function TabsList({ children, className }: TabsListProps) {
  const ctx = useTabsCtx();
  const containerRef = useRef<HTMLDivElement | null>(null);

  const enabled = ctx.getEnabledValues();
  const indexOf = (v: string) => enabled.indexOf(v);

  const focusEdge = (edge: "home" | "end") => {
    if (!enabled.length) return;
    const v = edge === "home" ? enabled[0] : enabled[enabled.length - 1];
    ctx.getRefByValue(v)?.focus();
  };

  const move = (delta: 1 | -1) => {
    const i = indexOf(ctx.value);
    if (i === -1 || !enabled.length) return;
    const next = (i + delta + enabled.length) % enabled.length;
    const v = enabled[next];
    ctx.getRefByValue(v)?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const isH = ctx.orientation === "horizontal";
    if (e.key === "ArrowRight" && isH) {
      e.preventDefault();
      move(1);
    } else if (e.key === "ArrowLeft" && isH) {
      e.preventDefault();
      move(-1);
    } else if (e.key === "ArrowDown" && !isH) {
      e.preventDefault();
      move(1);
    } else if (e.key === "ArrowUp" && !isH) {
      e.preventDefault();
      move(-1);
    } else if (e.key === "Home") {
      e.preventDefault();
      focusEdge("home");
    } else if (e.key === "End") {
      e.preventDefault();
      focusEdge("end");
    }
  };

  const listCls = clsx(
    "relative flex gap-1",
    ctx.orientation === "horizontal" ? "flex-row" : "flex-col",
    ctx.variant === "underline" && "border-b border-white/10",
    className
  );

  return (
    <div
      role="tablist"
      aria-orientation={ctx.orientation}
      ref={containerRef}
      onKeyDown={onKeyDown}
      className={listCls}
    >
      {children}
    </div>
  );
}

export type TabsTriggerProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  value: string;
  disabled?: boolean;
  leading?: React.ReactNode;
  trailing?: React.ReactNode;
  className?: string;
};

export function TabsTrigger({ value, disabled, leading, trailing, className, ...rest }: TabsTriggerProps) {
  const ctx = useTabsCtx();
  const ref = useRef<HTMLButtonElement | null>(null);
  const selected = ctx.value === value;
  useEffect(() => {
    ctx.register(value, ref.current, !!disabled);
  }, [ctx, value, disabled]);

  const base = clsx(
    "relative select-none cursor-pointer outline-none",
    "whitespace-nowrap duration-300",
    ctx.size === "sm" && "px-3 py-1 rounded-4xl",
    ctx.size === "md" && "px-4 py-2 text-base rounded-lg",
    ctx.size === "lg" && "px-5 py-3 text-lg rounded-xl",
    ctx.variant === "underline" && "border-b-2 border-transparent data-[state=active]:border-white",
    ctx.variant === "soft" && "data-[state=active]:bg-white/10 hover:bg-white/5",
    ctx.variant === "solid" && "data-[state=active]:bg-accent data-[state=active]:text-on-accent text-white bg-neutral-800 hover:bg-accent-strong/90 z",
    disabled && "opacity-50 cursor-not-allowed",
    className
  );

  return (
    <button
      {...rest}
      ref={ref}
      role="tab"
      id={`${ctx.baseId}-tab-${value}`}
      aria-selected={selected}
      aria-controls={`${ctx.baseId}-panel-${value}`}
      tabIndex={selected ? 0 : -1}
      data-state={selected ? "active" : "inactive"}
      disabled={disabled}
      onClick={(e) => {
        rest.onClick && rest.onClick(e);
        if (!disabled) ctx.setValue(value);
      }}
      className={base}
    >
      <span className="inline-flex items-center gap-2">
        {leading}
        <span>{rest.children}</span>
        {trailing}
      </span>
    </button>
  );
}

export type TabsContentProps = {
  value: string;
  forceMount?: boolean;
  className?: string;
  children: React.ReactNode;
};

export function TabsContent({ value, forceMount, className, children }: TabsContentProps) {
  const ctx = useTabsCtx();
  const selected = ctx.value === value;
  const shouldMount = ctx.keepAlive || forceMount || selected;
  if (!shouldMount) return null;
  return (
    <div
      role="tabpanel"
      id={`${ctx.baseId}-panel-${value}`}
      aria-labelledby={`${ctx.baseId}-tab-${value}`}
      hidden={!selected}
      className={clsx("focus:outline-none w-full", className)}
    >
      {children}
    </div>
  );
}

export type DataTabItem = {
  value: string;
  label: React.ReactNode;
  content: React.ReactNode;
  disabled?: boolean;
  leading?: React.ReactNode;
  trailing?: React.ReactNode;
};

export type DataTabsProps = Omit<TabsRootProps, "children"> & {
  items: DataTabItem[];
  listClassName?: string;
  triggerClassName?: string;
  contentClassName?: string;
};

export function DataTabs({ items, listClassName, triggerClassName, contentClassName, ...root }: DataTabsProps) {
  return (
    <TabsRoot {...root}>
      <TabsList className={listClassName}>
        {items.map((it) => (
          <TabsTrigger key={it.value} value={it.value} disabled={it.disabled} leading={it.leading} trailing={it.trailing} className={triggerClassName}>
            {it.label}
          </TabsTrigger>
        ))}
      </TabsList>
      <div className="mt-4">
        {items.map((it) => (
          <TabsContent key={it.value} value={it.value} className={contentClassName}>
            {it.content}
          </TabsContent>
        ))}
      </div>
    </TabsRoot>
  );
}

export type TabsCardProps = {
  value: string;
  trigger: React.ReactNode;
  disabled?: boolean;
  children: React.ReactNode;
};

export type TabsCardsProps = Omit<TabsRootProps, "children"> & {
  children: React.ReactNode;
  listClassName?: string;
  triggerClassName?: string;
  contentClassName?: string;
};

export function TabsCard(_: TabsCardProps) {
  return null;
}

function isTabsCard(el: React.ReactNode): el is React.ReactElement<TabsCardProps> {
  return !!el && typeof el === "object" && (el as any).type === TabsCard;
}

export function TabsCards({ children, listClassName, triggerClassName, contentClassName, ...root }: TabsCardsProps) {
  const items = React.Children.toArray(children).filter(isTabsCard) as React.ReactElement<TabsCardProps>[];
  return (
    <TabsRoot {...root}>
      <TabsList className={`${listClassName} gap-3 flex-wrap py-5`}>
        {items.map((el) => (
          <TabsTrigger key={el.props.value} value={el.props.value} disabled={el.props.disabled} className={triggerClassName}>
            {el.props.trigger}
          </TabsTrigger>
        ))}
      </TabsList>
      <div className="w-full">
        {items.map((el) => (
          <TabsContent key={el.props.value} value={el.props.value} className={contentClassName}>
            {el.props.children}
          </TabsContent>
        ))}
      </div>
    </TabsRoot>
  );
}

function useTabsCtx() {
  const ctx = useContext(TabsCtx);
  if (!ctx) throw new Error("Tabs components must be used within <TabsRoot>");
  return ctx;
}


const Tabs = {
  Root: TabsRoot,
  List: TabsList,
  Trigger: TabsTrigger,
  Content: TabsContent,
  Data: DataTabs,
  Cards: TabsCards,
  Card: TabsCard,
};

export default Tabs;
