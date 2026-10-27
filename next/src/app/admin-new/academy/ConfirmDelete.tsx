"use client";

import { useState } from "react";
import { FiTrash2 } from "react-icons/fi";
import { btn } from "../vstudio-showcase/parts";
import Dialog from "../studio-scenes/Dialog";
import type { Course } from "./academyAdmin";

/**
 * Подтверждение удаления — своё окно, а не window.confirm: во встроенных
 * браузерах (Telegram на iPhone) confirm может не показаться и сразу вернуть
 * false — курс тогда нельзя было бы удалить с телефона.
 */
export default function ConfirmDelete({
  course,
  onConfirm,
  onClose,
}: {
  course: Course;
  /** Удалить; вернуть текст отказа или null (тогда окно закроет страница). */
  onConfirm: (course: Course) => Promise<string | null>;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const name = course.title ? `«${course.title}»` : `№${course.id}`;

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const problem = await onConfirm(course);
    if (problem) {
      setBusy(false);
      setError(problem);
    }
  };

  return (
    <Dialog
      title="Удалить курс?"
      busy={busy}
      onClose={onClose}
      onSubmit={() => void submit()}
      error={error}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={btn("plain", "lg")}>
            Отмена
          </button>
          <button type="submit" disabled={busy} className={btn("danger", "lg")}>
            <FiTrash2 className="h-4 w-4" aria-hidden />
            {busy ? "Удаляю…" : "Удалить насовсем"}
          </button>
        </>
      }
    >
      <p className="text-sm [overflow-wrap:anywhere]">
        Курс {name} будет удалён вместе с обложкой. Вернуть его будет нельзя.
      </p>
      {course.state === "live" && (
        <p className="text-sm text-status-wait">
          Курс сейчас на сайте — он пропадёт с /academy в течение минуты. Чтобы убрать его на время, нажмите «Скрыть».
        </p>
      )}
    </Dialog>
  );
}
