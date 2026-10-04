"use client";

import { useState } from "react";
import { adminApprovePublication, adminRejectPublication } from "@/lib/creators/adminApi";
import type { AdminPublication } from "@/lib/creators/adminTypes";
import type { CrError } from "@/lib/creators/types";
import ReasonDialog from "./ReasonDialog";
import { BTN_DANGER, BTN_OK, errText } from "./ui";

/**
 * Кнопки проверки публикации (ТЗ п.17). Проверять публикации может любой
 * сотрудник. Одна и та же пара кнопок стоит во вкладке «Публикации» и в
 * профиле креатора.
 */
export default function PublicationActions({
  row,
  onChange,
}: {
  row: AdminPublication;
  onChange: (row: AdminPublication) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<CrError | null>(null);
  const [rejecting, setRejecting] = useState(false);

  if (row.status !== "review") return null;

  const approve = async () => {
    setBusy(true);
    setError(null);
    const res = await adminApprovePublication(row.id);
    setBusy(false);
    if (res.ok) onChange(res.data);
    else setError(res.error);
  };

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-1.5">
        <button type="button" className={BTN_OK} disabled={busy} onClick={approve}>
          {busy ? "Сохраняю…" : "Одобрить"}
        </button>
        <button type="button" className={BTN_DANGER} disabled={busy} onClick={() => setRejecting(true)}>
          Отклонить
        </button>
      </div>
      {error && <p className="text-xs text-rose-300">{errText(error)}</p>}

      {rejecting && (
        <ReasonDialog
          title="Отклонить публикацию"
          description={
            <span className="break-all">
              {row.creator_name}: {row.url}
            </span>
          }
          reason="optional"
          reasonLabel="Причина — её увидит креатор"
          confirmLabel="Отклонить"
          danger
          onClose={() => setRejecting(false)}
          onSubmit={async (reason) => {
            const res = await adminRejectPublication(row.id, reason);
            if (!res.ok) return res.error;
            onChange(res.data);
            return null;
          }}
        />
      )}
    </div>
  );
}
