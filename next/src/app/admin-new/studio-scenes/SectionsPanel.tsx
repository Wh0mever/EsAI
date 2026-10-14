"use client";

import { FiEdit2, FiPlus } from "react-icons/fi";
import { CARD, Switch, btn } from "../vstudio-showcase/parts";
import { missingLangs, sectionName, type Section, type SectionCount } from "./scenesAdmin";

type Props = {
  /** В порядке библиотеки. */
  sections: Section[];
  counts: ReadonlyMap<number, SectionCount>;
  busy: ReadonlySet<number>;
  /** Раздел, сцены которого сейчас в фильтре. */
  active: number | null;
  onVisible: (section: Section, visible: boolean) => void;
  /** false — набрано не то: поле вернёт прежний порядок. */
  onSort: (section: Section, typed: string) => boolean;
  onEdit: (section: Section) => void;
  onShow: (section: Section) => void;
  onCreate: () => void;
};

/**
 * Разделы библиотеки — вкладки над сценами на сайте. Порядок — числом, как у
 * сцен; скрыть раздел — значит убрать с сайта и его сцены.
 */
export default function SectionsPanel({ sections, counts, busy, active, onVisible, onSort, onEdit, onShow, onCreate }: Props) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
        <h2 className="text-base font-semibold">Разделы</h2>
        <span className="min-w-0 flex-1 basis-60 text-xs text-muted-2">
          Вкладки библиотеки по порядку: меньше число — раньше. Скрытый раздел прячет с сайта и свои сцены.
        </span>
        <button type="button" onClick={onCreate} className={`${btn()} min-h-9`}>
          <FiPlus className="h-3.5 w-3.5" aria-hidden />
          Новый раздел
        </button>
      </div>

      {sections.length === 0 ? (
        <div className={`${CARD} p-4 text-sm text-muted-2`}>
          Разделов пока нет — сцены видны только во вкладке «Все». Создайте первый раздел.
        </div>
      ) : (
        <ul className={`${CARD} divide-y divide-border`}>
          {sections.map((section) => {
            const count = counts.get(section.id) ?? { total: 0, published: 0 };
            const langs = missingLangs(section);
            const locked = busy.has(section.id);
            return (
              <li key={section.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5">
                <button
                  type="button"
                  onClick={() => onShow(section)}
                  aria-pressed={active === section.id}
                  title="Показать сцены этого раздела"
                  className={`min-h-9 min-w-0 flex-1 basis-48 cursor-pointer text-left text-sm ${
                    active === section.id ? "font-semibold text-accent" : section.visible ? "text-foreground" : "text-muted"
                  }`}
                >
                  <span className="break-words">{sectionName(section) || section.slug}</span>
                  <span className="ml-2 inline-block text-[11px] font-normal text-muted-2">
                    {section.visible ? "" : "скрыт · "}сцен: {count.total} · видно: {section.visible ? count.published : 0}
                    {langs.length > 0 ? ` · нет ${langs.join(", ")}` : ""}
                  </span>
                </button>
                <label className="inline-flex items-center gap-2 text-xs text-muted">
                  Порядок
                  {/* key: ответ сервера (или откат после отказа) заменяет то, что набрано в поле. */}
                  <input
                    key={section.sort}
                    defaultValue={section.sort}
                    inputMode="numeric"
                    disabled={locked}
                    title="Меньше — раньше. Enter — сохранить, Esc — отменить"
                    onFocus={(e) => e.currentTarget.select()}
                    onBlur={(e) => {
                      const typed = e.currentTarget.value.trim();
                      if (typed === String(section.sort)) return;
                      if (typed === "" || !onSort(section, typed)) e.currentTarget.value = String(section.sort);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") e.currentTarget.blur();
                      if (e.key === "Escape") {
                        e.currentTarget.value = String(section.sort);
                        e.currentTarget.blur();
                      }
                    }}
                    className="h-9 w-20 rounded-lg border border-border bg-surface-2 px-2 text-center text-sm tabular-nums text-foreground outline-none focus:border-accent disabled:opacity-60 sm:h-8"
                  />
                </label>
                <Switch
                  on={section.visible}
                  label="Показан"
                  title="Скрытый раздел пропадает с сайта вместе со своими сценами"
                  disabled={locked}
                  onChange={(visible) => onVisible(section, visible)}
                />
                <button type="button" onClick={() => onEdit(section)} disabled={locked} className={`${btn()} min-h-9`}>
                  <FiEdit2 className="h-3.5 w-3.5" aria-hidden />
                  Изменить
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
