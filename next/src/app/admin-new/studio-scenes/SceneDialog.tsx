"use client";

import { useEffect, useState } from "react";
import { FiRefreshCw, FiUpload, FiX } from "react-icons/fi";
import { Badge, INPUT_LG, Switch, btn } from "../vstudio-showcase/parts";
import Dialog from "./Dialog";
import { Choice, Field, ScenePreview } from "./sceneParts";
import {
  createBody,
  fmtMb,
  previewFileError,
  previewLabel,
  previewSecondsError,
  savedNote,
  sceneChanges,
  sceneWarnings,
  sectionOption,
  validateScene,
  type AudienceOption,
  type Limits,
  type Scene,
  type SceneForm,
  type Section,
} from "./scenesAdmin";

/** Ответ страницы на запрос окна: сцена с сервера или текст отказа. */
export type Saved = { scene: Scene | null; error: string | null };

/** Выбранный, но ещё не отправленный ролик превью. */
type Staged = {
  file: File;
  /** Ссылка для просмотра в окне; null — файл отклонён до отправки. */
  url: string | null;
  seconds: number | null;
  /** Браузер ещё читает длительность. */
  reading: boolean;
  error: string | null;
};

/** Длительность ролика по его заголовку; null — браузер не прочитал (тогда проверит сервер). */
function readSeconds(src: string): Promise<number | null> {
  return new Promise((resolve) => {
    const video = document.createElement("video");
    let settled = false;
    // Битый файл может не ответить ни тем, ни другим событием — не ждём вечно.
    const timer = setTimeout(() => finish(null), 10_000);
    function finish(value: number | null) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      video.removeAttribute("src");
      video.load();
      resolve(value);
    }
    video.preload = "metadata";
    video.muted = true;
    video.onloadedmetadata = () => finish(Number.isFinite(video.duration) ? video.duration : null);
    video.onerror = () => finish(null);
    video.src = src;
  });
}

const LEGEND = "mb-1 text-xs font-semibold uppercase tracking-wide text-muted-2";
const TEXTAREA = `${INPUT_LG} mt-1.5 block w-full resize-y leading-relaxed`;

type Props = {
  /**
   * null — новая сцена. Созданную страница передаёт сюда же: если ролик не
   * ушёл, повторное «Сохранить» дошлёт его к ней, а не создаст вторую.
   */
  scene: Scene | null;
  initial: SceneForm;
  sections: Section[];
  audiences: AudienceOption[];
  aspects: string[];
  limits: Limits;
  onCreate: (body: Record<string, unknown>) => Promise<Saved>;
  onUpdate: (scene: Scene, changes: Record<string, unknown>) => Promise<Saved>;
  onUpload: (scene: Scene, file: File) => Promise<Saved>;
  onRebuild: (scene: Scene) => Promise<Saved>;
  /** Всё сохранено: окно закрывается, страница показывает итог (null — нечего сказать). */
  onDone: (note: string | null) => void;
  onClose: () => void;
};

/**
 * Сцена библиотеки целиком: названия на трёх языках, место в библиотеке,
 * формат, английские промпты для моделей и ролик превью. Одно «Сохранить»
 * создаёт или правит сцену и следом отправляет выбранный ролик — так новая
 * сцена с превью появляется за один шаг.
 */
export default function SceneDialog({
  scene,
  initial,
  sections,
  audiences,
  aspects,
  limits,
  onCreate,
  onUpdate,
  onUpload,
  onRebuild,
  onDone,
  onClose,
}: Props) {
  const [form, setForm] = useState(initial);
  const [staged, setStaged] = useState<Staged | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const creating = scene === null;

  // Ссылка на выбранный файл держит его в памяти — отпускаем, как только он не нужен.
  const stagedUrl = staged?.url ?? null;
  useEffect(
    () => () => {
      if (stagedUrl) URL.revokeObjectURL(stagedUrl);
    },
    [stagedUrl],
  );

  const set = (patch: Partial<SceneForm>) => setForm((prev) => ({ ...prev, ...patch }));

  const choose = async (file: File) => {
    setError(null);
    const problem = previewFileError(file, limits);
    if (problem) {
      setStaged({ file, url: null, seconds: null, reading: false, error: problem });
      return;
    }
    const url = URL.createObjectURL(file);
    setStaged({ file, url, seconds: null, reading: true, error: null });
    const seconds = await readSeconds(url);
    // Пока читали, могли выбрать другой файл — его не трогаем.
    setStaged((prev) =>
      prev && prev.file === file
        ? { ...prev, seconds, reading: false, error: previewSecondsError(seconds, limits) }
        : prev,
    );
  };

  const submit = async () => {
    if (busy) return;
    const problem = validateScene(form, limits, aspects, creating) ?? staged?.error ?? null;
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    let current = scene;
    const created = current === null;
    if (current === null) {
      setBusy("Создаю…");
      const res = await onCreate(createBody(form, limits));
      if (!res.scene) {
        setBusy(null);
        setError(res.error);
        return;
      }
      current = res.scene;
      // Дальше окно правит созданную сцену, а у неё порядок обязателен: пустое
      // «в конец» превращаем в то место, куда её поставил сервер.
      const sort = String(current.sort);
      setForm((prev) => (prev.sort.trim() ? prev : { ...prev, sort }));
    } else {
      const changes = sceneChanges(current, form, limits);
      if (Object.keys(changes).length > 0) {
        setBusy("Сохраняю…");
        const res = await onUpdate(current, changes);
        if (!res.scene) {
          setBusy(null);
          setError(res.error);
          return;
        }
        current = res.scene;
      } else if (!staged) {
        // Ничего не поменяли — пустую правку сервер всё равно отклонил бы.
        onDone(null);
        return;
      }
    }
    if (staged) {
      setBusy("Загружаю ролик…");
      const res = await onUpload(current, staged.file);
      if (!res.scene) {
        setBusy(null);
        setError(`${created ? "Сцена создана" : "Сцена сохранена"}, но ролик не загрузился: ${res.error}`);
        return;
      }
      current = res.scene;
    }
    setBusy(null);
    onDone(savedNote(current, { created, uploaded: staged !== null }));
  };

  const rebuild = async () => {
    if (!scene || busy) return;
    setBusy("Пересобираю…");
    setError(null);
    const res = await onRebuild(scene);
    setBusy(null);
    if (!res.scene) setError(res.error);
  };

  const warnings = sceneWarnings(form);
  const preview = scene?.preview ?? null;
  const label = preview ? previewLabel(preview) : null;
  const maxMb = Math.floor(limits.previewMaxBytes / (1024 * 1024));
  const price = scene && scene.credits !== null ? `цена для пользователя: ${scene.credits} кр` : "";
  const facts = scene
    ? [`Код: ${scene.slug}`, `в мультфильмах: ${scene.usedIn}`, price].filter(Boolean).join(" · ")
    : "Новая сцена не видна в библиотеке, пока вы её не опубликуете.";

  return (
    <Dialog
      wide
      title={scene ? `Сцена «${scene.title}»` : "Новая сцена"}
      subtitle={facts}
      busy={busy !== null}
      onClose={onClose}
      onSubmit={() => void submit()}
      error={error}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy !== null} className={btn("plain", "lg")}>
            Отмена
          </button>
          <button type="submit" disabled={busy !== null} className={btn("primary", "lg")}>
            {busy ?? (creating ? "Создать" : "Сохранить")}
          </button>
        </>
      }
    >
      <fieldset className="min-w-0 space-y-3">
        <legend className={LEGEND}>Названия</legend>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Название *">
            <input
              type="text"
              value={form.title}
              maxLength={limits.titleMax}
              placeholder="Например: Полёт над городом"
              onChange={(e) => set({ title: e.target.value })}
              className={`${INPUT_LG} mt-1.5 block w-full`}
            />
          </Field>
          <Field label="Подпись" hint="Короткое пояснение под названием: «Герой появляется на крыше».">
            <input
              type="text"
              value={form.subtitle}
              maxLength={limits.subtitleMax}
              onChange={(e) => set({ subtitle: e.target.value })}
              className={`${INPUT_LG} mt-1.5 block w-full`}
            />
          </Field>
          <Field label="Название (EN)">
            <input
              type="text"
              lang="en"
              value={form.titleEn}
              maxLength={limits.titleMax}
              onChange={(e) => set({ titleEn: e.target.value })}
              className={`${INPUT_LG} mt-1.5 block w-full`}
            />
          </Field>
          <Field label="Подпись (EN)">
            <input
              type="text"
              lang="en"
              value={form.subtitleEn}
              maxLength={limits.subtitleMax}
              onChange={(e) => set({ subtitleEn: e.target.value })}
              className={`${INPUT_LG} mt-1.5 block w-full`}
            />
          </Field>
          <Field label="Название (KG)">
            <input
              type="text"
              lang="ky"
              value={form.titleKg}
              maxLength={limits.titleMax}
              onChange={(e) => set({ titleKg: e.target.value })}
              className={`${INPUT_LG} mt-1.5 block w-full`}
            />
          </Field>
          <Field label="Подпись (KG)">
            <input
              type="text"
              lang="ky"
              value={form.subtitleKg}
              maxLength={limits.subtitleMax}
              onChange={(e) => set({ subtitleKg: e.target.value })}
              className={`${INPUT_LG} mt-1.5 block w-full`}
            />
          </Field>
        </div>
        {/* Помощника перевода в проекте нет (см. отчёт EF_F1) — кнопки «перевести» не обещаем. */}
        <p className="text-xs text-muted-2">
          EN и KG заполняются вручную. Пустое поле — на этом языке сайт покажет русский текст.
        </p>
        {creating && (
          <Field
            label="Код (необязательно)"
            hint="Латиница, цифры и дефисы, например night-flight. Пусто — сделается из названия. После создания не меняется."
          >
            <input
              type="text"
              lang="en"
              value={form.slug}
              maxLength={limits.slugMax}
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              onChange={(e) => set({ slug: e.target.value })}
              className={`${INPUT_LG} mt-1.5 block w-full font-mono`}
            />
          </Field>
        )}
      </fieldset>

      <fieldset className="min-w-0 space-y-3">
        <legend className={LEGEND}>В библиотеке</legend>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Раздел" hint="Вкладка библиотеки. Без раздела сцена видна только во «Всех».">
            <select
              value={form.sectionId ?? ""}
              onChange={(e) => set({ sectionId: e.target.value ? Number(e.target.value) : null })}
              className={`${INPUT_LG} mt-1.5 block w-full cursor-pointer`}
            >
              <option value="">Без раздела</option>
              {sections.map((section) => (
                <option key={section.id} value={section.id}>
                  {sectionOption(section)}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Порядок"
            hint={creating ? "Меньше — выше в разделе. Пусто — в конец раздела." : "Меньше — выше в разделе."}
          >
            <input
              type="text"
              inputMode="numeric"
              value={form.sort}
              placeholder={creating ? "в конец" : undefined}
              onChange={(e) => set({ sort: e.target.value })}
              className={`${INPUT_LG} mt-1.5 block w-full tabular-nums`}
            />
          </Field>
        </div>
        <Choice label="Для кого" options={audiences} value={form.audience} onChange={(audience) => set({ audience })} />
        <p className="text-xs text-muted-2">
          По ней сцена попадает под переключатель «Для детей / Для взрослых» библиотеки; от неё же зависит стиль кадра.
        </p>
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          <Switch
            on={form.published}
            label="Опубликована"
            title="Видна в библиотеке, когда у неё есть превью и её раздел не скрыт"
            onChange={(published) => set({ published })}
          />
          <Switch
            on={form.pick}
            label="«Выбор EsAI»"
            title="Подборка наверху библиотеки"
            onChange={(pick) => set({ pick })}
          />
        </div>
      </fieldset>

      <fieldset className="min-w-0 space-y-3">
        <legend className={LEGEND}>Съёмка</legend>
        <div className="grid gap-3 sm:grid-cols-2">
          <Choice
            label="Пропорции"
            options={aspects.map((aspect) => ({ key: aspect, label: aspect }))}
            value={form.aspect}
            onChange={(aspect) => set({ aspect })}
          />
          <Field
            label="Длительность, с"
            hint={`От ${limits.durationMin} до ${limits.durationMax} секунд; обычно ${limits.durationDefault}.`}
          >
            <input
              type="text"
              inputMode="numeric"
              value={form.duration}
              onChange={(e) => set({ duration: e.target.value })}
              className={`${INPUT_LG} mt-1.5 block w-full tabular-nums`}
            />
          </Field>
        </div>
        <p className="text-xs text-muted-2">
          Модели кадра и видео — те же, что у всей библиотеки: здесь они не выбираются.
        </p>
      </fieldset>

      <fieldset className="min-w-0 space-y-3">
        <legend className={LEGEND}>Промпты для моделей — по-английски</legend>
        <Field
          label="Промпт сцены *"
          hint="Что происходит в кадре, от третьего лица. Героя обозначайте словом character: «The character flies above the city at sunset». Пользователь промпт не видит."
        >
          <textarea
            lang="en"
            rows={4}
            value={form.scenePrompt}
            maxLength={limits.scenePromptMax}
            onChange={(e) => set({ scenePrompt: e.target.value })}
            className={TEXTAREA}
          />
        </Field>
        <Field
          label="Промпт движения"
          hint="Чем движение отличается от кадра: «camera slowly pushes in, cape flutters». Пусто — возьмётся промпт сцены."
        >
          <textarea
            lang="en"
            rows={3}
            value={form.motionPrompt}
            maxLength={limits.motionPromptMax}
            onChange={(e) => set({ motionPrompt: e.target.value })}
            className={TEXTAREA}
          />
        </Field>
        {warnings.length > 0 && (
          <ul
            role="status"
            className="space-y-1 rounded-xl border border-status-wait/30 bg-status-wait/10 px-3 py-2 text-xs text-status-wait"
          >
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}
      </fieldset>

      <fieldset className="min-w-0 space-y-3">
        <legend className={LEGEND}>Превью</legend>
        <p className="text-xs text-muted-2">
          Ролик, который пользователь видит до съёмки: MP4 (H.264), до {maxMb} МБ, от {limits.previewMinSeconds} до{" "}
          {limits.previewMaxSeconds} секунд. Лёгкую копию для ленты, обложку и миниатюру сервер сделает сам; пока они
          собираются, библиотека играет сам ролик.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          {preview?.video && (
            <div className="flex min-w-0 flex-col gap-2">
              <ScenePreview preview={preview} className={`rounded-xl ${staged ? "opacity-50" : ""}`} />
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-2">
                <span>{staged ? "Сейчас — заменится выбранным" : "Сейчас"}</span>
                {label && (
                  <Badge tone={label.tone} title={label.title}>
                    {label.label}
                  </Badge>
                )}
                {scene && preview.state === "partial" && (
                  <button type="button" onClick={() => void rebuild()} disabled={busy !== null} className={btn()}>
                    <FiRefreshCw className="h-3.5 w-3.5" aria-hidden />
                    Пересобрать
                  </button>
                )}
              </div>
              {preview.notes.length > 0 && <p className="text-xs text-status-wait">{preview.notes.join(". ")}</p>}
            </div>
          )}

          {staged && (
            <div className="flex min-w-0 flex-col gap-2">
              {staged.url ? (
                <video
                  src={staged.url}
                  controls
                  muted
                  playsInline
                  preload="metadata"
                  className="aspect-video w-full rounded-xl bg-black object-contain"
                />
              ) : null}
              <div className="flex items-start gap-2 text-xs">
                <span className="min-w-0 flex-1 break-words text-muted">
                  {staged.file.name} · {fmtMb(staged.file.size)}
                  {staged.reading ? " · читаю длительность…" : ""}
                  {staged.seconds !== null ? ` · ${Math.round(staged.seconds * 10) / 10} с` : ""}
                </span>
                <button
                  type="button"
                  onClick={() => setStaged(null)}
                  disabled={busy !== null}
                  aria-label="Не загружать этот ролик"
                  title="Не загружать"
                  className="-m-1 flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 sm:h-7 sm:w-7"
                >
                  <FiX className="h-4 w-4" aria-hidden />
                </button>
              </div>
              {staged.error ? (
                <p className="text-xs text-status-fail">{staged.error}</p>
              ) : (
                <p className="text-xs text-muted-2">
                  Ролик уйдёт на сервер по «{creating ? "Создать" : "Сохранить"}».
                </p>
              )}
            </div>
          )}
        </div>

        <label
          className={`${btn("plain", "lg")} relative w-full hover:text-foreground focus-within:border-accent sm:w-auto ${
            busy !== null ? "pointer-events-none opacity-50" : ""
          }`}
        >
          <FiUpload className="h-4 w-4" aria-hidden />
          {preview?.video || staged ? "Выбрать другой ролик" : "Выбрать ролик"}
          <input
            type="file"
            accept="video/mp4,.mp4"
            disabled={busy !== null}
            className="sr-only"
            onChange={(e) => {
              const file = e.currentTarget.files?.[0] ?? null;
              // Тот же файл ещё раз — тоже выбор: без сброса браузер промолчит.
              e.currentTarget.value = "";
              if (file) void choose(file);
            }}
          />
        </label>
      </fieldset>
    </Dialog>
  );
}
