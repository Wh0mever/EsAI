"use client";

import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiExternalLink, FiPlus } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import ErrorNote from "@/components/creators/shared/ErrorNote";
import LoadMore from "@/components/creators/shared/LoadMore";
import StatusBadge from "@/components/creators/shared/StatusBadge";
import { useDialogFocus } from "@/components/creators/shared/useDialogFocus";
import { addPublication, listPublications } from "@/lib/creators/api";
import { errorText } from "@/lib/creators/errors";
import { fmtDate, isHttpUrl } from "@/lib/creators/format";
import { NETWORKS, networkLabel } from "@/lib/creators/labels";
import type { CrError, Network, Publication } from "@/lib/creators/types";
import { BTN_GHOST, BTN_PRIMARY, Empty, INPUT, ListSkeleton, Note } from "./ui";
import { usePagedList } from "./usePagedList";

const URL_MAX = 500;
const DESCRIPTION_MAX = 500;

/**
 * «Мои публикации» (ТЗ п.16): список и форма «+ Добавить публикацию». Новая
 * публикация уходит на проверку; в прогресс уровня идут только подтверждённые.
 * Файлы не загружаются — публикация это ссылка.
 */
export default function PublicationsTab({ blocked }: { blocked: boolean }) {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const fetchPage = useCallback((page: number) => listPublications({ page }), []);
  const list = usePagedList<Publication>(fetchPage);
  const [formOpen, setFormOpen] = useState(false);
  const [added, setAdded] = useState(false);

  const title = t("dash.pubs.title", { defaultValue: "Мои публикации" });
  const addLabel = t("dash.pubs.add", { defaultValue: "Добавить публикацию" });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-foreground">{title}</h2>
        {!blocked && (
          <button
            type="button"
            onClick={() => {
              setAdded(false);
              setFormOpen(true);
            }}
            className={BTN_PRIMARY}
          >
            <FiPlus aria-hidden />
            {addLabel}
          </button>
        )}
      </div>

      {added && <Note tone="ok">{t("dash.pubs.added", { defaultValue: "Публикация отправлена на проверку." })}</Note>}

      {list.loading ? (
        <ListSkeleton />
      ) : list.error ? (
        <ErrorNote error={list.error} onRetry={list.reload} />
      ) : list.rows.length === 0 ? (
        <Empty>
          {t("dash.pubs.empty", {
            defaultValue: "Публикаций пока нет. Добавьте ссылку на свой пост — мы проверим её.",
          })}
        </Empty>
      ) : (
        <>
          <ul className="flex flex-col gap-2">
            {list.rows.map((row) => (
              <li key={row.id} className="rounded-2xl border border-border bg-surface p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-foreground">{networkLabel(t, row.network)}</span>
                  <StatusBadge kind="publication" status={row.status} />
                </div>
                <a
                  href={row.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1.5 inline-flex max-w-full items-start gap-1 break-all text-sm text-accent hover:underline"
                >
                  <span className="min-w-0">{row.url}</span>
                  <FiExternalLink className="mt-0.5 shrink-0" aria-hidden />
                </a>
                {row.description && <p className="mt-1.5 break-words text-sm text-muted">{row.description}</p>}
                {row.status === "rejected" && row.reject_reason && (
                  <p className="mt-1.5 break-words text-sm text-status-fail">
                    {t("dash.common.reason", { defaultValue: "Причина: {{reason}}", reason: row.reject_reason })}
                  </p>
                )}
                <div className="mt-1.5 text-xs text-muted-2">{fmtDate(row.created_at, i18n.language)}</div>
              </li>
            ))}
          </ul>
          {list.moreError && <ErrorNote error={list.moreError} />}
          <LoadMore shown={list.rows.length} total={list.count} loading={list.loadingMore} onMore={list.loadMore} />
        </>
      )}

      <p className="text-xs text-muted">
        {t("dash.pubs.note", { defaultValue: "В прогресс уровня идут только подтверждённые публикации." })}
      </p>

      <Modal open={formOpen} onClose={() => setFormOpen(false)} title={addLabel} size="md" mobileFull>
        {formOpen && (
          <PublicationForm
            onCancel={() => setFormOpen(false)}
            onAdded={(row) => {
              list.prepend(row);
              setAdded(true);
              setFormOpen(false);
            }}
          />
        )}
      </Modal>
    </div>
  );
}

function PublicationForm({ onAdded, onCancel }: { onAdded: (row: Publication) => void; onCancel: () => void }) {
  const { t } = useTranslation("creators", { useSuspense: false });
  const [network, setNetwork] = useState<Network | "">("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  // Код ошибки и поле, к которому она относится: текст берётся по коду.
  const [fieldError, setFieldError] = useState<{ field: "network" | "url"; code: string } | null>(null);
  const [error, setError] = useState<CrError | null>(null);
  // Форма живёт, только пока окно открыто: появилась — фокус в окно, исчезла — обратно на кнопку.
  const formRef = useDialogFocus<HTMLFormElement>(true);

  const submit = async () => {
    setError(null);
    const link = url.trim();
    if (!network) {
      setFieldError({ field: "network", code: "network_invalid" });
      return;
    }
    if (!isHttpUrl(link) || link.length > URL_MAX) {
      setFieldError({ field: "url", code: "url_invalid" });
      return;
    }
    setFieldError(null);
    setBusy(true);
    const res = await addPublication({ network, url: link, description: description.trim() });
    setBusy(false);
    if (res.ok) {
      onAdded(res.data);
      return;
    }
    const code = res.error.code;
    if (code === "network_invalid") setFieldError({ field: "network", code });
    else if (code === "url_invalid" || code === "publication_duplicate") setFieldError({ field: "url", code });
    else setError(res.error);
  };

  const networkTitle = t("dash.pubs.network", { defaultValue: "Социальная сеть" });
  const urlTitle = t("dash.pubs.url", { defaultValue: "Ссылка на публикацию" });
  const descriptionTitle = t("dash.pubs.description", { defaultValue: "Краткое описание" });

  return (
    <form
      ref={formRef}
      tabIndex={-1}
      className="flex flex-col gap-3 outline-none"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy) void submit();
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">{networkTitle}</span>
        <select
          value={network}
          onChange={(e) => {
            setNetwork(e.target.value as Network | "");
            setFieldError(null);
          }}
          disabled={busy}
          aria-invalid={fieldError?.field === "network"}
          className={INPUT}
        >
          {/* Сеть заранее не выбрана: человек должен назвать её сам. */}
          <option value="" disabled>
            {t("dash.pubs.network_placeholder", { defaultValue: "Выберите соцсеть" })}
          </option>
          {NETWORKS.map((key) => (
            <option key={key} value={key}>
              {networkLabel(t, key)}
            </option>
          ))}
        </select>
        {fieldError?.field === "network" && <Note tone="fail">{errorText(t, { code: fieldError.code })}</Note>}
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">{urlTitle}</span>
        <input
          type="url"
          inputMode="url"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setFieldError(null);
          }}
          placeholder="https://"
          maxLength={URL_MAX}
          autoComplete="off"
          disabled={busy}
          aria-invalid={fieldError?.field === "url"}
          className={INPUT}
        />
        {fieldError?.field === "url" && <Note tone="fail">{errorText(t, { code: fieldError.code })}</Note>}
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">{descriptionTitle}</span>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={DESCRIPTION_MAX}
          rows={3}
          disabled={busy}
          className={`${INPUT} resize-y`}
        />
      </label>

      {error && <ErrorNote error={error} />}

      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy} className={BTN_PRIMARY}>
          {busy
            ? t("dash.common.sending", { defaultValue: "Отправляю…" })
            : t("dash.pubs.submit", { defaultValue: "Отправить на проверку" })}
        </button>
        <button type="button" onClick={onCancel} disabled={busy} className={BTN_GHOST}>
          {t("dash.common.cancel", { defaultValue: "Отмена" })}
        </button>
      </div>
    </form>
  );
}
