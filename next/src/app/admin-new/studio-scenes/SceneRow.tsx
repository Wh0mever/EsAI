"use client";

import { FiEdit2, FiRefreshCw, FiTrash2 } from "react-icons/fi";
import { Badge, CARD, Switch, btn } from "../vstudio-showcase/parts";
import { ScenePreview } from "./sceneParts";
import { missingLangs, previewLabel, stateLabel, type AudienceOption, type Scene } from "./scenesAdmin";

type Props = {
  scene: Scene;
  audiences: AudienceOption[];
  /** Запрос по этой сцене в пути — её поля ждут ответа. */
  busy: boolean;
  onPublish: (scene: Scene, published: boolean) => void;
  onPick: (scene: Scene, pick: boolean) => void;
  /** Порядок, как его набрали; проверка — у страницы. false — не принят: поле вернёт прежний. */
  onSort: (scene: Scene, typed: string) => boolean;
  onRebuild: (scene: Scene) => void;
  onEdit: (scene: Scene) => void;
  onDelete: (scene: Scene) => void;
};

/** Сцена в списке: что видят посетители и быстрые правки — публикация, «Выбор EsAI», порядок. */
export default function SceneRow({ scene, audiences, busy, onPublish, onPick, onSort, onRebuild, onEdit, onDelete }: Props) {
  const state = stateLabel(scene);
  const preview = previewLabel(scene.preview);
  const langs = missingLangs(scene);
  const audience = audiences.find((option) => option.key === scene.audience)?.label ?? scene.audience;
  const facts = [
    audience,
    scene.aspect,
    `${scene.duration} с`,
    scene.credits !== null ? `${scene.credits} кр` : "",
    scene.usedIn > 0 ? `в мультфильмах: ${scene.usedIn}` : "",
  ].filter(Boolean);

  const commitSort = (field: HTMLInputElement) => {
    const typed = field.value.trim();
    if (typed === String(scene.sort)) return;
    // Пустое поле — не «нулевое место», а «передумал».
    if (typed === "" || !onSort(scene, typed)) field.value = String(scene.sort);
  };

  return (
    <li className={`${CARD} flex flex-col gap-3 p-3 sm:flex-row sm:items-start`}>
      <ScenePreview
        preview={scene.preview}
        className={`shrink-0 rounded-xl sm:w-56 ${scene.state === "live" ? "" : "opacity-70"}`}
      />

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-start gap-2">
          <div className="min-w-0 flex-1 basis-48">
            <div className="break-words text-sm font-semibold text-foreground">{scene.title}</div>
            {scene.subtitle && <div className="break-words text-xs text-muted">{scene.subtitle}</div>}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={state.tone} title={state.title}>
              {state.label}
            </Badge>
            {preview && (
              <Badge tone={preview.tone} title={preview.title}>
                {preview.label}
              </Badge>
            )}
            {scene.pick && (
              <Badge tone="accent" title="Стоит в подборке наверху библиотеки">
                Выбор EsAI
              </Badge>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-2">
          <span className="font-mono" title="Код сцены — по нему её находят «Популярное» и сохранённые ленты">
            {scene.slug}
          </span>
          <span aria-hidden>·</span>
          <span>{facts.join(" · ")}</span>
          {langs.length > 0 && (
            <span
              className="rounded border border-border px-1"
              title="Нет перевода — на этих языках сайт покажет русский текст"
            >
              нет {langs.join(", ")}
            </span>
          )}
        </div>

        {scene.scenePrompt && (
          <p lang="en" className="line-clamp-2 break-words text-xs text-muted" title={scene.scenePrompt}>
            {scene.scenePrompt}
          </p>
        )}

        <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-2">
          <label className="inline-flex items-center gap-2 text-xs text-muted">
            Порядок
            {/* key: ответ сервера (или откат после отказа) заменяет то, что набрано в поле. */}
            <input
              key={scene.sort}
              defaultValue={scene.sort}
              inputMode="numeric"
              disabled={busy}
              title="Меньше — выше в разделе. Enter — сохранить, Esc — отменить"
              onFocus={(e) => e.currentTarget.select()}
              onBlur={(e) => commitSort(e.currentTarget)}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
                if (e.key === "Escape") {
                  e.currentTarget.value = String(scene.sort);
                  e.currentTarget.blur();
                }
              }}
              className="h-9 w-20 rounded-lg border border-border bg-surface-2 px-2 text-center text-sm tabular-nums text-foreground outline-none focus:border-accent disabled:opacity-60 sm:h-8"
            />
          </label>
          <Switch
            on={scene.published}
            label="Опубликована"
            title="Видна в библиотеке, когда у неё есть превью и её раздел не скрыт"
            disabled={busy}
            onChange={(published) => onPublish(scene, published)}
          />
          <Switch
            on={scene.pick}
            label="«Выбор EsAI»"
            title="Подборка наверху библиотеки"
            disabled={busy}
            onChange={(pick) => onPick(scene, pick)}
          />
          <div className="flex flex-wrap gap-2 sm:ml-auto">
            {scene.preview.state === "partial" && (
              <button type="button" onClick={() => onRebuild(scene)} disabled={busy} className={btn()}>
                <FiRefreshCw className="h-3.5 w-3.5" aria-hidden />
                Пересобрать
              </button>
            )}
            <button type="button" onClick={() => onEdit(scene)} disabled={busy} className={`${btn()} min-h-9`}>
              <FiEdit2 className="h-3.5 w-3.5" aria-hidden />
              Изменить
            </button>
            {/* Взятую сцену кнопка не прячет: нажатие объяснит, почему нельзя и что делать вместо. */}
            <button
              type="button"
              onClick={() => onDelete(scene)}
              disabled={busy}
              title={
                scene.canDelete
                  ? "Удалить сцену насовсем"
                  : `Сцену уже взяли в мультфильмы (${scene.usedIn}) — удалить нельзя. Снимите её с публикации`
              }
              className={`${btn("danger")} min-h-9`}
            >
              <FiTrash2 className="h-3.5 w-3.5" aria-hidden />
              Удалить
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}
