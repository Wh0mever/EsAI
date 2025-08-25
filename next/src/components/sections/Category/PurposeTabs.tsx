"use client";

import React, { useMemo } from "react";
import { Button } from "@/components/ui/buttons/Buttons";

type HasPurpose = { purpose: string };

type Props<T extends HasPurpose = HasPurpose> = {
  value: string;
  onChange: (purpose: string) => void;
  purposes?: string[];          // если передан, используется он
  data?: T[];                   // иначе берём уникальные purpose из data
  className?: string;
  showAll?: boolean;
  allLabel?: string;            // по умолчанию "Все"
};

const PurposeTabs = <T extends HasPurpose>({
  value,
  onChange,
  purposes,
  data,
  className = "",
  showAll = false,
  allLabel = "All",
}: Props<T>) => {
  const keys = useMemo(() => {
    const base = purposes
      ? purposes
      : Array.from(new Set((data ?? []).map((i) => i.purpose)));
    return showAll ? [allLabel, ...base] : base;
  }, [purposes, data, showAll, allLabel]);

  if (!keys.length) return null;

  return (
    <div className={`flex flex-wrap justify-center gap-2 py-5 w-full lg:w-7/12 mx-auto ${className}`}>
      {keys.map((k) => (
        <Button
          key={k}
          className={`px-4 py-1.5 rounded-xl text-sm font-medium transition-colors ${
            value === k
              ? "bg-indigo-600/50 text-white"
              : "bg-neutral-800/25 text-gray-300 hover:bg-neutral-700"
          }`}
          onClick={() => onChange(k)}
        >
          {k}
        </Button>
      ))}
    </div>
  );
};

export default PurposeTabs;
