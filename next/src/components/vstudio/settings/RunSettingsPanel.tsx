"use client";

/**
 * Правая колонка «Параметры запуска» (§9.2): вид, модель, пропорции,
 * длительность и качество с ценами-подсказками, звук, «Как модель использует
 * ваши фото», «Дополнительно». На телефоне то же самое живёт в SettingsSheet.
 *
 * Два слоя:
 *   - RunSettingsView — чистое представление на пропсах (ничего не знает о сторе);
 *   - RunSettingsPanel — подключение к стору студии: {state, dispatch} пропсами
 *     или из контекста VideoStudio (FE-1). Действия — только из VsAction
 *     (lib/vstudio/types.ts).
 *
 * Цены под значениями — подсказки из ModelJSON.price (images=0). Итог с
 * фото-референсами и проверками — только quote на кнопке «Создать» (FE-3).
 */
import { useCallback, useMemo, type Dispatch } from "react";
import { useTranslation } from "react-i18next";
import { FiInfo, FiX } from "react-icons/fi";
import { quoteBodyFrom, quoteKey, trackVs } from "@/lib/vstudio/api";
import type {
  ComposerState,
  ModelJSON,
  ModelsResponse,
  QuoteBody,
  QuoteJSON,
  ShotParams,
  VsAction,
  VsError,
  VsKind,
  VsState,
} from "@/lib/vstudio/types";
import { useVStudioOptional } from "../context";
import { isGuest, useVStudioModels } from "../hooks/useVStudioModels";
import { VS_ICON_BTN } from "../ui/skin";
import AdvancedSection from "./AdvancedSection";
import AspectPicker from "./AspectPicker";
import AudioToggle from "./AudioToggle";
import DurationPicker from "./DurationPicker";
import InputsExplainer from "./InputsExplainer";
import KindTabs from "./KindTabs";
import ModelPicker, { openModelPicker } from "./ModelPicker";
import ResolutionPicker from "./ResolutionPicker";
import { Reason, cx } from "./SettingsBits";
import { countInputs, findModel, forcedDuration, modelsFor, shownParams } from "./settingsModel";
import { tx } from "./settingsText";
import { selectKind, selectModel, useRunSettingsSync } from "./useRunSettingsSync";

/* ------------------------------------------------------------------ */
/* Представление                                                       */
/* ------------------------------------------------------------------ */

/**
 * Разделы идут один под другим через волосяную линию. shrink-0 у разделов:
 * иначе в колонке с прокруткой flex сжимает раскрывающиеся блоки (grid-rows)
 * и обрезает их содержимое.
 */
const SECTIONS =
  "flex shrink-0 flex-col [&>*]:shrink-0 [&>*]:py-4 [&>*+*]:border-t [&>*+*]:border-border [&>*:first-child]:pt-0 [&>*:last-child]:pb-0";

export type RunSettingsViewProps = {
  models: Pick<ModelsResponse, "video" | "image"> | null;
  composer: Pick<ComposerState, "kind" | "model" | "params" | "tray" | "frames">;
  /** Свежий quote (key совпал с текущим телом) — для режима и меток в объяснении. */
  quote?: QuoteJSON | null;
  loading?: boolean;
  error?: VsError | null;
  onRetry?: () => void;
  onKind: (kind: VsKind) => void;
  onModel: (id: string) => void;
  onParams: (patch: Partial<ShotParams>) => void;
  onLocked: (model: ModelJSON) => void;
  /** panel — правая колонка; sheet — нижняя шторка на телефоне (без своего заголовка). */
  variant?: "panel" | "sheet";
  /** Кнопка «×» в заголовке (выезжающая панель на 768–1279). */
  onClose?: () => void;
  /** false — вкладки вида стоят в другом месте (верхняя строка ленты). */
  showKindTabs?: boolean;
  className?: string;
};

export function RunSettingsView({
  models,
  composer,
  quote,
  loading,
  error,
  onRetry,
  onKind,
  onModel,
  onParams,
  onLocked,
  variant = "panel",
  onClose,
  showKindTabs = true,
  className,
}: RunSettingsViewProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { kind } = composer;
  const list = modelsFor(models, kind);
  const model = findModel(models, composer.model, kind);
  const counts = countInputs(composer.tray, composer.frames);
  const p = shownParams(model, kind, composer.params);
  const forced = forcedDuration(kind, model, counts);
  const priceAspect = p.aspect_ratio;

  return (
    // h-full у колонки: прокручивается список параметров, а заголовок с «×» остаётся на месте.
    // Своего фона у панели нет: стекло даёт тот, кто её показывает (колонка, выезжающая панель, шторка).
    <div className={cx("flex min-h-0 flex-col", variant === "panel" && "h-full", className)}>
      {variant === "panel" && (
        // Высота как у верхней строки ленты (h-14): линии двух колонок сходятся.
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border pl-4 pr-2">
          <h2 className="vs-display min-w-0 flex-1 text-base text-foreground">{tx(t, "settings.title")}</h2>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label={tx(t, "settings.hide")}
              title={tx(t, "settings.hide")}
              className={VS_ICON_BTN}
            >
              <FiX className="size-4" aria-hidden />
            </button>
          )}
        </div>
      )}

      {/* В шторке прокручивает сама шторка (BottomSheet) и отступы — её же. */}
      <div
        className={cx(
          "flex flex-col",
          variant === "panel" ? "min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-5 pt-4" : "pb-2 pt-1",
        )}
      >
        {showKindTabs && (
          <KindTabs
            value={kind}
            onChange={onKind}
            counts={models ? { video: models.video.length, image: models.image.length } : undefined}
            className="mb-4 shrink-0"
          />
        )}

        <div className={SECTIONS}>
          <ModelPicker
            kind={kind}
            models={list}
            value={model?.id ?? null}
            counts={counts}
            onSelect={onModel}
            onLocked={onLocked}
            loading={loading || (!models && !error)}
            error={error}
            onRetry={onRetry}
          />

          {model && (
            <>
              <AspectPicker
                kind={kind}
                model={model}
                value={p.aspect_ratio}
                onChange={(v) => onParams({ aspect_ratio: v })}
                duration={forced ?? p.duration}
                resolution={p.resolution}
              />

              {kind === "video" && (
                <>
                  <DurationPicker
                    model={model}
                    value={p.duration}
                    onChange={(v) => onParams({ duration: v })}
                    resolution={p.resolution}
                    aspect={priceAspect}
                    forced={forced}
                  />
                  <ResolutionPicker
                    model={model}
                    value={p.resolution}
                    onChange={(v) => onParams({ resolution: v })}
                    duration={forced ?? p.duration}
                    aspect={priceAspect}
                  />
                  <AudioToggle model={model} value={p.generate_audio} onChange={(v) => onParams({ generate_audio: v })} />
                </>
              )}

              <InputsExplainer
                kind={kind}
                model={model}
                tray={composer.tray}
                frames={composer.frames}
                quote={quote}
                onPickModel={openModelPicker}
              />

              <AdvancedSection key={model.id} model={model} kind={kind} params={composer.params} onChange={onParams} />

              <div className="flex gap-2">
                <FiInfo className="mt-px size-3.5 shrink-0 text-muted-2" aria-hidden />
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  {kind === "video" && <Reason tone="muted">{tx(t, "settings.priceHint")}</Reason>}
                  <Reason tone="muted">{tx(t, "settings.exact")}</Reason>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Подключение к стору                                                 */
/* ------------------------------------------------------------------ */

export type RunSettingsPanelProps = {
  /** Стор студии; без пропсов — из контекста useVStudio() (внутри <VideoStudio>). */
  state?: VsState;
  dispatch?: Dispatch<VsAction>;
  variant?: "panel" | "sheet";
  onClose?: () => void;
  showKindTabs?: boolean;
  className?: string;
};

/** Свежий quote: цена и метки годятся, только если тело запроса не менялось. */
export function freshQuote(state: Pick<VsState, "quote" | "composer" | "project">): QuoteJSON | null {
  const q = state.quote;
  if (q.status !== "ready" || !q.data || !q.key) return null;
  const body = quoteBodyFrom(state.composer, state.project?.uid ?? null);
  if (!body) return null;
  if (quoteKey(body) === q.key) return q.data;
  // Запасная textarea: цена посчитана по телу с prompt_text вместо prompt_doc.
  // Модель, параметры и материалы те же — сравниваем тело без текста.
  try {
    const sent = JSON.parse(q.key) as Record<string, unknown>;
    if (typeof sent.prompt_text !== "string") return null;
    const { prompt_text: _sentText, ...sentRest } = sent;
    const { prompt_doc: _doc, ...bodyRest } = body;
    void _sentText;
    void _doc;
    return quoteKey(sentRest as unknown as QuoteBody) === quoteKey(bodyRest as unknown as QuoteBody) ? q.data : null;
  } catch {
    return null;
  }
}

/**
 * Модель под замком: гостю — окно входа (контейнер сам сохранит черновик и
 * отметит vstudio_auth_prompt), остальным — существующий пэйволл premium_locked.
 * Модель при этом не выбирается.
 */
export function openLockedModel(
  dispatch: Dispatch<VsAction>,
  opts: { requireAuth?: () => boolean; guest?: boolean } = {},
): void {
  if (opts.requireAuth) {
    if (!opts.requireAuth()) return;
  } else if (opts.guest ?? isGuest()) {
    dispatch({ type: "ui/auth", open: true });
    return;
  }
  dispatch({ type: "ui/paywall", paywall: { reason: "premium_locked" } });
  trackVs("vstudio_paywall");
}

/** Стор из пропсов, иначе из контекста студии. */
export function useStudioStore(state?: VsState, dispatch?: Dispatch<VsAction>) {
  const ctx = useVStudioOptional();
  const s = state ?? ctx?.state;
  const d = dispatch ?? ctx?.dispatch;
  if (!s || !d) throw new Error("vstudio/settings: нужен {state, dispatch} или <VideoStudio> вокруг");
  return { state: s, dispatch: d, ctx };
}

export default function RunSettingsPanel(props: RunSettingsPanelProps) {
  const { variant = "panel", onClose, showKindTabs, className } = props;
  const { state, dispatch, ctx } = useStudioStore(props.state, props.dispatch);
  useRunSettingsSync(state, dispatch);
  const { loading, error, reload } = useVStudioModels();
  const { composer, models, project } = state;
  const quoteState = state.quote;
  const quote = useMemo(
    () => freshQuote({ quote: quoteState, composer, project }),
    [quoteState, composer, project],
  );

  const current = { kind: composer.kind, model: composer.model, params: composer.params };
  const onKind = (kind: VsKind) => selectKind(dispatch, models, current, kind);
  const onModel = (id: string) => selectModel(dispatch, models, current, id);
  const onParams = useCallback((patch: Partial<ShotParams>) => dispatch({ type: "composer/params", params: patch }), [dispatch]);
  const onLocked = () => openLockedModel(dispatch, { requireAuth: ctx?.actions.requireAuth });

  return (
    <RunSettingsView
      models={models}
      composer={composer}
      quote={quote}
      loading={loading}
      error={error}
      onRetry={() => void reload()}
      onKind={onKind}
      onModel={onModel}
      onParams={onParams}
      onLocked={onLocked}
      variant={variant}
      onClose={onClose}
      showKindTabs={showKindTabs}
      className={className}
    />
  );
}
