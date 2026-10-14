"use client";

import { useState } from "react";
import { INPUT_LG, Switch, btn } from "../vstudio-showcase/parts";
import Dialog from "./Dialog";
import { Field } from "./sceneParts";
import {
  formFromSection,
  newSectionForm,
  sectionChanges,
  sectionCreateBody,
  validateSection,
  type Limits,
  type Section,
  type SectionForm,
} from "./scenesAdmin";

type Props = {
  /** null — новый раздел. */
  section: Section | null;
  limits: Limits;
  /** null — сохранено (окно закроется), иначе текст отказа. */
  onSubmit: (section: Section | null, body: Record<string, unknown>) => Promise<string | null>;
  onClose: () => void;
};

/**
 * Раздел библиотеки — вкладка над сценами: название на трёх языках, значок,
 * порядок и показ. Удаления нет и у сервера: раздел скрывают, и вместе с ним
 * со страницы пропадают его сцены.
 */
export default function SectionDialog({ section, limits, onSubmit, onClose }: Props) {
  const [form, setForm] = useState<SectionForm>(() => (section ? formFromSection(section) : newSectionForm()));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const creating = section === null;

  const set = (patch: Partial<SectionForm>) => setForm((prev) => ({ ...prev, ...patch }));

  const submit = async () => {
    if (busy) return;
    const problem = validateSection(form, limits, creating);
    if (problem) {
      setError(problem);
      return;
    }
    const body = section ? sectionChanges(section, form, limits) : sectionCreateBody(form, limits);
    if (section && Object.keys(body).length === 0) {
      onClose();
      return;
    }
    setBusy(true);
    setError(null);
    const failure = await onSubmit(section, body);
    setBusy(false);
    if (failure) setError(failure);
    else onClose();
  };

  return (
    <Dialog
      title={section ? `Раздел «${section.title}»` : "Новый раздел"}
      subtitle={
        section
          ? `Код: ${section.slug}`
          : "Вкладка библиотеки сцен. Сцены в неё ставятся в окне сцены, полем «Раздел»."
      }
      busy={busy}
      onClose={onClose}
      onSubmit={() => void submit()}
      error={error}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={btn("plain", "lg")}>
            Отмена
          </button>
          <button type="submit" disabled={busy} className={btn("primary", "lg")}>
            {busy ? "Сохраняю…" : creating ? "Создать" : "Сохранить"}
          </button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-[1fr_7rem]">
        <Field label="Название *">
          <input
            type="text"
            value={form.title}
            maxLength={limits.sectionTitleMax}
            placeholder="Например: Космос"
            onChange={(e) => set({ title: e.target.value })}
            className={`${INPUT_LG} mt-1.5 block w-full`}
          />
        </Field>
        <Field label="Значок">
          <input
            type="text"
            value={form.emoji}
            placeholder="🚀"
            onChange={(e) => set({ emoji: e.target.value })}
            className={`${INPUT_LG} mt-1.5 block w-full text-center`}
          />
        </Field>
        <Field label="Название (EN)">
          <input
            type="text"
            lang="en"
            value={form.titleEn}
            maxLength={limits.sectionTitleMax}
            onChange={(e) => set({ titleEn: e.target.value })}
            className={`${INPUT_LG} mt-1.5 block w-full`}
          />
        </Field>
        <Field label="Порядок" hint={creating ? "Пусто — в конец" : "Меньше — раньше"}>
          <input
            type="text"
            inputMode="numeric"
            value={form.sort}
            onChange={(e) => set({ sort: e.target.value })}
            className={`${INPUT_LG} mt-1.5 block w-full tabular-nums`}
          />
        </Field>
        <Field label="Название (KG)">
          <input
            type="text"
            lang="ky"
            value={form.titleKg}
            maxLength={limits.sectionTitleMax}
            onChange={(e) => set({ titleKg: e.target.value })}
            className={`${INPUT_LG} mt-1.5 block w-full`}
          />
        </Field>
      </div>
      <p className="text-xs text-muted-2">
        EN и KG заполняются вручную. Пустое поле — на этом языке сайт покажет русское название.
      </p>
      <div>
        <Switch
          on={form.visible}
          label="Показан на сайте"
          title="Скрытый раздел прячет и свои сцены"
          onChange={(visible) => set({ visible })}
        />
        <p className="mt-1 text-xs text-muted-2">
          Скрытый раздел пропадает из библиотеки вместе со своими сценами. Готовые мультфильмы с ними остаются целы.
        </p>
      </div>
    </Dialog>
  );
}
