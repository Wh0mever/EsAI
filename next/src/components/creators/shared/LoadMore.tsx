"use client";

import { useTranslation } from "react-i18next";
import { fmtInt } from "@/lib/creators/format";

type Props = {
  /** Сколько строк уже на экране. */
  shown: number;
  /** Сколько всего (count из ответа списка). */
  total: number;
  loading: boolean;
  onMore: () => void;
};

/** «Ещё (показано X из N)» под списком; когда показано всё — ничего. */
export default function LoadMore({ shown, total, loading, onMore }: Props) {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  if (shown >= total) return null;

  return (
    <div className="flex justify-center">
      <button
        type="button"
        onClick={onMore}
        disabled={loading}
        className="cursor-pointer rounded-xl border border-border px-6 py-2.5 text-sm text-muted transition-colors hover:border-accent hover:text-accent disabled:cursor-default disabled:opacity-50"
      >
        {loading
          ? t("common.loading_more", { defaultValue: "Загружаю…" })
          : t("common.more", {
              defaultValue: "Ещё (показано {{shown}} из {{total}})",
              shown: fmtInt(shown, i18n.language),
              total: fmtInt(total, i18n.language),
            })}
      </button>
    </div>
  );
}
