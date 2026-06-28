"use client";

import { useState } from "react";
import { Button } from "@/components/ui/buttons/Buttons";
import formEntries from "@/tools/formEntries";

type Props = {
  onSubmit: (data: Record<string, any>) => Promise<void> | void;
  submitLabel: React.ReactNode;
  className?: string;
  children: React.ReactNode;
  disabled?: boolean;
  loadingLabel?: React.ReactNode;
};

export default function SmartForm({
  onSubmit,
  submitLabel,
  className,
  children,
  disabled = false,
  loadingLabel,
}: Props) {
  const [loading, setLoading] = useState(false);

  const handle = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    try {
      const data = formEntries(e.currentTarget);
      await onSubmit(data);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handle} className={className}>
      <fieldset disabled={loading || disabled} className="w-full">
        <div className="flex flex-col gap-8">{children}</div>
        <Button
          className="w-full px-3 py-2 rounded-xl mt-5 bg-accent text-on-accent hover:bg-accent-strong duration-300"
          type="submit"
          disabled={loading || disabled}
        >
          <div className="flex items-center justify-center gap-2">
            {loading && (
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
                <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
              </svg>
            )}
            <span>{loading ? loadingLabel ?? submitLabel : submitLabel}</span>
          </div>
        </Button>
      </fieldset>
    </form>
  );
}
