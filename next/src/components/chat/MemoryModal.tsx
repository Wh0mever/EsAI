"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal, ConfirmationModal } from "@/components/dialog/Dialog";
import { fetchData } from "@/tools/fetchData";
import { FiTrash2, FiCpu, FiEdit3 } from "react-icons/fi";

type MemoryItem = {
  id: string | number;
  content: string;
  category?: string;
  source?: string;
  importance?: number | string;
  updated_at?: string;
};

type MemoryResponse = {
  memory_enabled: boolean;
  items: MemoryItem[];
};

type Props = {
  open: boolean;
  onClose: () => void;
};

/**
 * MemoryModal — управление «памятью» ассистента (как настройки памяти ChatGPT).
 *  - GET    /api/users/memory/          — загрузить флаг + список фактов
 *  - PATCH  /api/users/memory/toggle/   — включить/выключить память
 *  - DELETE /api/users/memory/<id>/     — удалить отдельный факт
 *  - POST   /api/users/memory/clear/    — очистить всё (с подтверждением)
 * Все вызовы авторизованные (fetchData authed=true). Модалка открывается
 * только для авторизованных пользователей (точка входа в ChatSidebar).
 */
export default function MemoryModal({ open, onClose }: Props) {
  const { t } = useTranslation("common");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [deletingId, setDeletingId] = useState<string | number | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);

  // Человеческие русские подписи для категорий.
  const categoryLabel = (cat?: string): string => {
    switch ((cat || "other").toLowerCase()) {
      case "identity":
        return t("memory.cat_identity", { defaultValue: "О вас" });
      case "work":
        return t("memory.cat_work", { defaultValue: "Работа" });
      case "preference":
        return t("memory.cat_preference", { defaultValue: "Предпочтения" });
      case "project":
        return t("memory.cat_project", { defaultValue: "Проект" });
      default:
        return t("memory.cat_other", { defaultValue: "Прочее" });
    }
  };

  const sourceLabel = (src?: string): string => {
    if ((src || "").toLowerCase() === "manual")
      return t("memory.source_manual", { defaultValue: "вручную" });
    return t("memory.source_auto", { defaultValue: "авто" });
  };

  // Загрузка при открытии.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    (async () => {
      try {
        const res = await fetchData<MemoryResponse>("users/memory/", "GET", null, true);
        if (cancelled) return;
        if (res?.ok && res.data) {
          setEnabled(Boolean(res.data.memory_enabled));
          setItems(Array.isArray(res.data.items) ? res.data.items : []);
        } else {
          setError(t("memory.load_error", { defaultValue: "Не удалось загрузить память" }));
        }
      } catch {
        if (!cancelled)
          setError(t("memory.load_error", { defaultValue: "Не удалось загрузить память" }));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, t]);

  const toggleMemory = async () => {
    if (toggling) return;
    const next = !enabled;
    setToggling(true);
    setEnabled(next); // оптимистично
    try {
      const res = await fetchData("users/memory/toggle/", "PATCH", { enabled: next }, true);
      if (!res?.ok) {
        setEnabled(!next); // откат
        setError(t("memory.toggle_error", { defaultValue: "Не удалось изменить настройку" }));
      }
    } catch {
      setEnabled(!next);
      setError(t("memory.toggle_error", { defaultValue: "Не удалось изменить настройку" }));
    } finally {
      setToggling(false);
    }
  };

  const deleteItem = async (id: string | number) => {
    if (deletingId != null) return;
    setDeletingId(id);
    setError("");
    try {
      const res = await fetchData(`users/memory/${id}/`, "DELETE", null, true);
      if (res?.ok) {
        setItems((prev) => prev.filter((x) => String(x.id) !== String(id)));
      } else {
        setError(t("memory.delete_error", { defaultValue: "Не удалось удалить факт" }));
      }
    } catch {
      setError(t("memory.delete_error", { defaultValue: "Не удалось удалить факт" }));
    } finally {
      setDeletingId(null);
    }
  };

  const clearAll = async () => {
    if (clearing) return;
    setClearing(true);
    setError("");
    try {
      const res = await fetchData("users/memory/clear/", "POST", {}, true);
      if (res?.ok) {
        setItems([]);
      } else {
        setError(t("memory.clear_error", { defaultValue: "Не удалось очистить память" }));
      }
    } catch {
      setError(t("memory.clear_error", { defaultValue: "Не удалось очистить память" }));
    } finally {
      setClearing(false);
      setClearOpen(false);
    }
  };

  return (
    <>
      <Modal
        title={t("memory.title", { defaultValue: "Память" })}
        open={open}
        onClose={onClose}
        size="md"
      >
        <div className="p-1 sm:p-2">
          {/* Описание */}
          <p className="text-sm text-muted mb-4">
            {t("memory.subtitle", {
              defaultValue:
                "ESAI запоминает важные детали из ваших диалогов, чтобы отвечать точнее.",
            })}
          </p>

          {/* Тумблер «Память включена» */}
          <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface-2 px-3 py-3 mb-4">
            <div className="flex items-center gap-2 min-w-0">
              <FiCpu className="text-accent shrink-0" />
              <div className="min-w-0">
                <div className="text-sm font-medium text-foreground">
                  {t("memory.enabled_label", { defaultValue: "Память включена" })}
                </div>
                <div className="text-xs text-muted-2">
                  {t("memory.enabled_hint", {
                    defaultValue: "Когда выключено — новые факты не сохраняются.",
                  })}
                </div>
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-label={t("memory.enabled_label", { defaultValue: "Память включена" })}
              onClick={toggleMemory}
              disabled={toggling || loading}
              className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors cursor-pointer disabled:opacity-60 ${
                enabled ? "bg-accent" : "bg-surface-3 border border-border"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                  enabled ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
          </div>

          {/* Ошибка */}
          {error && (
            <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-500 text-sm px-3 py-2">
              {error}
            </div>
          )}

          {/* Загрузка */}
          {loading && (
            <div className="py-8 text-center text-muted">
              {t("common.loading", { defaultValue: "Загрузка..." })}
            </div>
          )}

          {/* Список фактов */}
          {!loading && (
            <>
              <div className="flex items-center justify-between mb-2">
                <div className="text-[11px] uppercase tracking-wide text-muted-2">
                  {t("memory.facts_title", { defaultValue: "Что я помню" })}
                </div>
                {items.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setClearOpen(true)}
                    className="inline-flex items-center gap-1.5 text-xs text-rose-500 hover:text-rose-600 transition-colors cursor-pointer"
                  >
                    <FiTrash2 className="text-sm" />
                    {t("memory.clear_all", { defaultValue: "Очистить всё" })}
                  </button>
                )}
              </div>

              {items.length === 0 ? (
                <div className="rounded-xl border border-dashed border-border bg-surface-2/40 px-4 py-8 text-center">
                  <div className="mx-auto w-10 h-10 rounded-full bg-accent-soft text-accent grid place-items-center text-lg mb-3">
                    <FiCpu />
                  </div>
                  <p className="text-sm text-muted">
                    {t("memory.empty", {
                      defaultValue:
                        "Память пуста. Расскажите о себе в чате или напишите «Запомни …».",
                    })}
                  </p>
                </div>
              ) : (
                <ul className="space-y-2">
                  {items.map((it) => (
                    <li
                      key={String(it.id)}
                      className="group flex items-start gap-2 rounded-xl border border-border bg-surface-2 px-3 py-2.5"
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-foreground break-words">{it.content}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <span className="inline-flex items-center rounded-full bg-accent-soft text-accent text-[10px] font-medium px-2 py-0.5">
                            {categoryLabel(it.category)}
                          </span>
                          <span className="inline-flex items-center gap-1 text-[10px] text-muted-2">
                            <FiEdit3 className="text-[10px]" />
                            {sourceLabel(it.source)}
                          </span>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => deleteItem(it.id)}
                        disabled={deletingId != null}
                        className="shrink-0 p-1.5 rounded-md text-muted hover:text-rose-500 hover:bg-surface-2 transition-colors cursor-pointer disabled:opacity-60"
                        title={t("memory.delete", { defaultValue: "Удалить" })}
                        aria-label={t("memory.delete", { defaultValue: "Удалить" })}
                      >
                        <FiTrash2 className="text-sm" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </Modal>

      <ConfirmationModal
        isOpen={clearOpen}
        title={t("memory.clear_confirm_title", { defaultValue: "Очистить всю память?" })}
        description={t("memory.clear_confirm_desc", {
          defaultValue: "Все сохранённые факты будут удалены безвозвратно.",
        })}
        confirmText={t("common.yes", { defaultValue: "Да" })}
        confirmLoadingText={t("common.loading", { defaultValue: "Загрузка..." })}
        cancelText={t("common.no", { defaultValue: "Нет" })}
        onConfirm={clearAll}
        onCancel={() => setClearOpen(false)}
        confirmDisabled={clearing}
      />
    </>
  );
}
