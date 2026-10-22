"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiLogIn, FiPlus, FiScissors } from "react-icons/fi";
import PaywallModal from "@/components/chat/PaywallModal";
import TopUpModal from "@/components/chat/TopUpModal";
import BottomSheet from "@/components/vstudio/BottomSheet";
import VStudioShell, { useVsBreakpoint } from "@/components/vstudio/VStudioShell";
import { useVisualViewport } from "@/components/vstudio/hooks/useVisualViewport";
import { prefersReducedMotion } from "@/components/vstudio/ui/useAutoplayAllowed";
import {
  VS_BTN_GHOST,
  VS_BTN_GOLD,
  VS_CARD,
  VS_FOCUS,
  VS_H2,
  VS_SECTION,
  VS_SEG_THUMB,
  VS_SEG_TRACK,
  VS_SUB,
  vx,
} from "@/components/vstudio/ui/skin";
import { rememberReturnPath } from "@/tools/authNext";
import MergeConfirmDialog from "./MergeConfirmDialog";
import MergeDock, { type MergePrimary } from "./MergeDock";
import MergeRail from "./MergeRail";
import MergeResult from "./MergeResult";
import MergeSoundPanel from "./MergeSoundPanel";
import MergeTimeline, { TimelineSkeleton } from "./MergeTimeline";
import MergeTopBar, { MergeErrorBanner, MergeHeader, signInHref } from "./MergeTopBar";
import SourcePicker, { PickerSkeleton } from "./SourcePicker";
import { useUploadBadge } from "./UploadPanel";
import { soundStep } from "./audioLogic";
import { MERGE_PATH, blockText, isActive, type AddPlace, type LocalBlock } from "./mergeLogic";
import type { MergeSourceCard } from "./mergeTypes";
import { useMerge } from "./useMerge";
import { useMergeAudio } from "./useMergeAudio";

/**
 * Страница «Склейка видео» (/merge): свои готовые ролики из видеостудии,
 * мультстудии и чата и загруженные файлы — в один. Каркас тот же, что у студий (VStudioShell):
 * слева «Мои склейки» (на узком — шторка), сверху название и баланс, в
 * середине выбор роликов и порядок фрагментов, внизу док с форматом,
 * заполнением кадра, итогом и «Склеить · 20 кр».
 *
 * С 1024 px выбор роликов — колонка слева от ленты (она стоит на месте, пока
 * лента прокручивается); уже — два вида одной кнопкой: «Склейка» и
 * «Добавить видео». Пока склейка идёт или готова, править нечего: на экране
 * итог и список фрагментов без кнопок.
 *
 * «Звук» (голос за кадром, музыка, звук роликов) открывается из дока: с
 * 1024 px — в той же левой колонке вместо выбора роликов (лента на виду:
 * видно, с какого фрагмента голос), уже — нижней шторкой.
 */
const noop = () => {};

export default function MergeStudio() {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const m = useMerge();
  const { actions } = m;
  const breakpoint = useVsBreakpoint();
  // Высота оболочки — видимая часть окна: на телефоне с клавиатурой док остаётся над ней.
  useVisualViewport({ cssVars: true });
  const feedScrollRef = useRef<HTMLDivElement | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const [railOpen, setRailOpen] = useState(false);
  // Телефон и планшет: что на экране — лента склейки или выбор роликов.
  const [view, setView] = useState<"timeline" | "picker">("timeline");
  /** Что сказать диктору: добавили, загрузили, удалили своё видео. */
  const [added, setAdded] = useState("");
  const pickerHeading = useId();
  const timelineHeading = useId();
  const uploadButtonId = useId();
  // Загрузка видна и тогда, когда на телефоне открыта лента, а не выбор роликов.
  const uploadBadge = useUploadBadge(m.upload, Boolean(m.uploadError));
  const project = m.project;
  const audio = useMergeAudio({
    projectId: m.openId,
    status: project?.status ?? null,
    summary: project?.audio ?? null,
    items: m.edit.items,
    enabled: m.authed === true && !m.loading,
    ensureSaved: actions.ensureSaved,
    onPaywall: actions.showPaywall,
    onBalance: actions.applyBalance,
    onSettled: actions.refreshBalance,
    onProjectChanged: actions.refreshProject,
    parked: m.parked,
    onIdle: actions.soundIdle,
  });
  /** Панель «Звук» открыта (колонка с 1024 px или шторка уже). */
  const [soundOpen, setSoundOpen] = useState(false);
  // Открыли другую склейку или начали новую — панель прежней не всплывает в ней сама.
  // Из «новой» в только что заведённую (первое сохранение) — та же склейка. Склейку
  // закрыли на время её удаления, а сервер отказал — панель снова открыта, как была.
  const [soundFor, setSoundFor] = useState(m.openId);
  /** Чья панель была открыта, когда склейку закрыли на время удаления. */
  const [soundKept, setSoundKept] = useState<string | null>(null);
  const soundSwitch = soundStep(soundFor, m.openId, m.parked, soundKept);
  if (soundSwitch !== "same") {
    setSoundFor(m.openId);
    if (soundSwitch === "park") setSoundKept(soundOpen ? soundFor : null);
    else setSoundKept(null);
    if (soundSwitch === "park" || soundSwitch === "reset") setSoundOpen(false);
    else if (soundSwitch === "restore") setSoundOpen(true);
  }
  const soundPanelId = useId();
  const soundHeading = useId();
  const soundButtonId = useId();
  // С 1024 px лента и левая колонка рядом — звук встаёт в колонку, уже — шторкой.
  const soundInColumn = breakpoint === "desktop" || breakpoint === "laptop";

  // Файл, брошенный мимо зоны загрузки (другая вкладка, лента, готовая склейка), браузер
  // открыл бы вместо страницы — со всей несохранённой правкой. Ловим его на всей странице.
  useEffect(() => {
    const guard = (e: globalThis.DragEvent) => {
      if (e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files")) e.preventDefault();
    };
    window.addEventListener("dragover", guard);
    window.addEventListener("drop", guard);
    return () => {
      window.removeEventListener("dragover", guard);
      window.removeEventListener("drop", guard);
    };
  }, []);

  const active = isActive(project?.status ?? null);
  const showEditor = m.authed === true && !m.loading && !m.opening && m.editable;
  const showResult = m.authed === true && !m.loading && !m.opening && Boolean(project) && !m.editable;
  // Склейка пошла или открыли готовую — звук не правится, панель не нужна.
  const soundShown = soundOpen && showEditor && !m.running;

  const openSound = () => {
    setSoundOpen(true);
    if (!soundInColumn) return;
    // Колонка сменилась панелью — фокус на её заголовок: Tab пойдёт по звуку, а не с начала страницы.
    window.requestAnimationFrame(() => document.getElementById(soundHeading)?.focus({ preventScroll: true }));
  };

  const closeSound = () => {
    setSoundOpen(false);
    // Шторка возвращает фокус сама; панель в колонке исчезла — фокус обратно на «Звук» в доке.
    if (soundInColumn) window.requestAnimationFrame(() => document.getElementById(soundButtonId)?.focus({ preventScroll: true }));
  };

  /** «Добавить видео» из пустой панели: на её месте — выбор роликов. */
  const addFromSound = () => {
    setSoundOpen(false);
    setView("picker");
    window.requestAnimationFrame(() => document.getElementById(pickerHeading)?.focus({ preventScroll: true }));
  };

  const toTimeline = () => {
    setView("timeline");
    window.requestAnimationFrame(() => {
      timelineRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
      timelineRef.current?.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
    });
  };

  const newMerge = () => {
    actions.newMerge();
    setView("timeline");
    if (feedScrollRef.current) feedScrollRef.current.scrollTop = 0;
  };

  const open = (id: string) => {
    actions.open(id);
    setView("timeline");
    if (feedScrollRef.current) feedScrollRef.current.scrollTop = 0;
  };

  const untitled = (card: MergeSourceCard) => card.title.trim() || t("merge.untitled", { defaultValue: "Без названия" });

  const addSource = (card: MergeSourceCard, place: AddPlace) => {
    if (!actions.addSource(card, place)) return;
    // Ролик встал первым — голос остаётся у своего ролика, а не у нового первого.
    if (place === "start") audio.actions.followFragments({ kind: "insert", index: 0 });
    const title = untitled(card);
    setAdded(
      place === "start"
        ? t("merge.addedStart", { defaultValue: "Добавлено в начало: {{title}}", title })
        : t("merge.added", { defaultValue: "Добавлено: {{title}}", title }),
    );
  };

  const uploadFile = async (file: File) => {
    const card = await actions.uploadFile(file);
    if (card) {
      setAdded(
        t("merge.upload.done", {
          defaultValue: "Видео загружено: {{title}}. Добавьте его в начало или в конец склейки.",
          title: untitled(card),
        }),
      );
    }
  };

  const cancelUpload = () => {
    actions.cancelUpload();
    setAdded(t("merge.upload.cancelled", { defaultValue: "Загрузка отменена" }));
  };

  const removeUpload = async (card: MergeSourceCard) => {
    if (!(await actions.removeUpload(card))) return;
    setAdded(t("merge.upload.deleted", { defaultValue: "Видео удалено: {{title}}", title: untitled(card) }));
    // Карточка с кнопкой исчезла — фокус не должен упасть в начало страницы.
    const focused = document.activeElement;
    if (!focused || focused === document.body) document.getElementById(uploadButtonId)?.focus();
  };

  // С какого ролика голос — в окне подтверждения: номер голоса следует за роликом, но проверить это надо видеть.
  const voiceAt = audio.voice.ready ? audio.voiceStart : -1;
  const voiceItem = voiceAt >= 0 ? m.edit.items[voiceAt] : undefined;
  const voiceFrom = voiceItem
    ? { n: voiceAt + 1, title: voiceItem.title.trim() || t("merge.untitled", { defaultValue: "Без названия" }) }
    : null;

  // Голос или музыка ещё делаются (или свой трек загружается) — «Склеить» подождёт: сервер ответил бы audio_pending.
  const block: LocalBlock | null = m.block ?? (m.editable && audio.blocking ? { code: "audio_pending" } : null);
  const primary: MergePrimary =
    m.running || active
      ? { kind: "busy" }
      : block
        ? { kind: "off", price: m.price, reason: blockText(block) }
        : m.short > 0
          ? { kind: "short", price: m.price, missing: m.short }
          : { kind: "run", price: m.price };

  const top = {
    loading: m.loading,
    authed: m.authed,
    balance: m.balance?.balance ?? null,
    balanceFailed: m.balanceFailed,
    openId: m.openId,
    title: m.edit.title || project?.title || "",
    back: m.returnPath,
    onRename: actions.rename,
    onTopup: actions.openTopup,
  };

  const editor = (
    <>
      {project && (project.status === "failed" || project.status === "expired") && (
        <div className="mb-5">
          <MergeResult project={project} onNew={newMerge} onCopy={actions.copyProject} />
        </div>
      )}
      {/* Телефон и планшет: лента или выбор — одной кнопкой; с 1024 px обе колонки рядом. */}
      <div role="group" aria-label={t("merge.view", { defaultValue: "Что показать" })} className={vx("mb-4 grid grid-cols-2 gap-1 rounded-full p-1 lg:hidden", VS_SEG_TRACK)}>
        {(["timeline", "picker"] as const).map((v) => {
          const on = view === v;
          return (
            <button
              key={v}
              type="button"
              aria-pressed={on}
              onClick={() => setView(v)}
              className={vx(
                "inline-flex min-h-11 min-w-0 cursor-pointer items-center justify-center gap-1.5 rounded-full px-3 text-[13px] font-medium transition-colors",
                VS_FOCUS,
                on ? vx(VS_SEG_THUMB, "text-vs-accent") : "text-muted hover:text-foreground",
              )}
            >
              {v === "timeline" ? (
                <>
                  <FiScissors className="shrink-0" aria-hidden="true" />
                  <span className="truncate">{t("merge.viewTimeline", { defaultValue: "Склейка" })}</span>
                  <span className="tabular-nums text-muted-2">{m.edit.items.length}</span>
                </>
              ) : (
                <>
                  <FiPlus className="shrink-0" aria-hidden="true" />
                  <span className="truncate">{t("merge.tl.add", { defaultValue: "Добавить видео" })}</span>
                  {!on && uploadBadge && (
                    <span className={vx("shrink-0 tabular-nums", uploadBadge.failed ? "text-status-fail" : "text-muted-2")}>
                      {uploadBadge.text}
                    </span>
                  )}
                </>
              )}
            </button>
          );
        })}
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(300px,380px)_minmax(0,1fr)] lg:items-start xl:gap-8">
        <div
          className={vx(
            // Колонка выбора стоит на месте, пока лента прокручивается, и листается сама.
            // Нижний отступ — под док: пока страница не прокручена (короткая лента её и не
            // прокрутит), колонка начинается под заголовком и её низ уходит под док.
            "lg:sticky lg:top-6 lg:-mx-1 lg:max-h-[calc(var(--vvh,100dvh)_-_13rem)] lg:overflow-y-auto lg:overscroll-contain lg:px-1 lg:pb-32",
            view !== "picker" && "max-lg:hidden",
          )}
        >
          {soundShown && soundInColumn && (
            <div id={soundPanelId}>
              <MergeSoundPanel
                audio={audio}
                items={m.edit.items}
                price={m.price}
                variant="column"
                headingId={soundHeading}
                onClose={closeSound}
                onAdd={addFromSound}
              />
            </div>
          )}
          {/* Выбор остаётся смонтированным: вкладка, прокрутка и идущая загрузка видео не теряются. */}
          <div className={soundShown && soundInColumn ? "hidden" : undefined}>
            <SourcePicker
              tab={m.tab}
              sources={m.sources}
              counts={m.counts}
              items={m.edit.items}
              limits={m.limits}
              maxUploads={m.uploadLimits.max_per_project}
              onTab={actions.setTab}
              onAdd={addSource}
              onMore={actions.loadMoreSources}
              onReload={actions.reloadSources}
              uploads={{
                limits: m.uploadLimits,
                usage: m.uploadUsage,
                upload: m.upload,
                error: m.uploadError,
                canRetry: m.retryFile !== null,
                deleting: m.deletingUploads,
                deleteError: m.deleteError,
                onFile: (file) => void uploadFile(file),
                onRetry: () => {
                  if (m.retryFile) void uploadFile(m.retryFile);
                },
                onCancel: cancelUpload,
                onDismissError: actions.dismissUploadError,
                onDismissDeleteError: actions.dismissDeleteError,
                onDelete: (card) => void removeUpload(card),
              }}
              uploadButtonId={uploadButtonId}
              headingId={pickerHeading}
            />
          </div>
        </div>
        <div ref={timelineRef} className={vx("scroll-mt-6 scroll-mb-14", view !== "timeline" && "max-lg:hidden")}>
          <MergeTimeline
            items={m.edit.items}
            editable
            limits={m.limits}
            total={m.total}
            onMove={(from, to) => {
              actions.moveItem(from, to);
              audio.actions.followFragments({ kind: "move", from, to });
            }}
            onRemove={(index) => {
              actions.removeItem(index);
              audio.actions.followFragments({ kind: "remove", index });
            }}
            onAdd={() => setView("picker")}
            unsaved={m.unsaved}
            onRetrySave={actions.retrySave}
            headingId={timelineHeading}
          />
        </div>
      </div>
      <p className="sr-only" role="status" aria-live="polite">
        {added}
      </p>
      {/* Звук готов, загружен, убран — слышно и тогда, когда панель закрыта. */}
      <p className="sr-only" role="status" aria-live="polite">
        {audio.said}
      </p>
    </>
  );

  const result = project ? (
    <div className="mx-auto flex max-w-[920px] flex-col gap-6">
      <MergeResult project={project} onNew={newMerge} onCopy={actions.copyProject} />
      <div ref={timelineRef} className="scroll-mt-6">
        <MergeTimeline
          items={m.edit.items}
          editable={false}
          limits={m.limits}
          total={m.total}
          onMove={noop}
          onRemove={noop}
          headingId={timelineHeading}
        />
      </div>
    </div>
  ) : null;

  const feed = (
    // pb-6 к отступу оболочки (pb-10): вместе не меньше затухания над доком (56 px).
    <div className="flex flex-col pb-6">
      <header className={vx(VS_SECTION, "pt-5 sm:pt-8")}>
        <h1 className="vs-display text-[26px] leading-tight text-foreground sm:text-[32px]">
          {t("merge.name", { defaultValue: "Склейка видео" })}
        </h1>
        <p className={vx(VS_SUB, "mt-1.5 max-w-2xl")}>
          {t("merge.sub", {
            defaultValue:
              "Соберите в одно видео готовые ролики из видеостудии, мультстудии и чата или свои файлы: выберите фрагменты, расставьте по порядку — и скачайте.",
          })}
        </p>
      </header>
      <div className={vx(VS_SECTION, "mt-6 sm:mt-8")}>
        {m.authed === false ? (
          <GuestCard price={m.price} back={m.returnPath} />
        ) : showEditor ? (
          editor
        ) : showResult ? (
          result
        ) : (
          <WorkspaceSkeleton />
        )}
      </div>
    </div>
  );

  return (
    <VStudioShell
      breakpoint={breakpoint}
      // Лента во всю ширину колонки: поля и ширину секций задают себе сами (VS_SECTION).
      home
      rail={(v) => (
        <MergeRail
          variant={v}
          loading={m.loading}
          authed={m.authed}
          list={m.list}
          openId={m.openId}
          balance={m.balance?.balance ?? null}
          balanceFailed={m.balanceFailed}
          back={m.returnPath}
          onOpen={open}
          onNew={newMerge}
          onDelete={(id) => void actions.remove(id)}
          deleteError={m.projectDeleteError}
          onDismissDeleteError={actions.dismissProjectDeleteError}
          onMore={actions.loadMoreProjects}
          onReload={actions.reloadProjects}
          onTopup={actions.openTopup}
          onExpand={() => setRailOpen(true)}
          onNavigate={() => setRailOpen(false)}
        />
      )}
      railOpen={railOpen}
      onRailOpenChange={setRailOpen}
      header={<MergeHeader {...top} />}
      topBar={<MergeTopBar {...top} onMenu={() => setRailOpen(true)} />}
      banner={m.error ? <MergeErrorBanner banner={m.error} onClose={actions.dismissError} onOpen={open} /> : null}
      feed={feed}
      // Док — пока склейку можно править или она идёт; у готовой действия — в карточке результата.
      composer={
        m.authed === true && !m.loading && !m.opening && (m.editable || active) ? (
          <MergeDock
            aspect={m.edit.aspect}
            fit={m.edit.fit}
            locked={!m.editable || m.running}
            count={m.edit.items.length}
            total={m.total}
            primary={primary}
            saving={m.saving}
            onAspect={actions.setAspect}
            onFit={actions.setFit}
            onRun={() => {
              if (!block) actions.requestRun();
            }}
            onTotal={toTimeline}
            sound={{
              // Крутилка на «Звуке» — и пока заказ ещё в пути, а не только когда сервер сказал «делается».
              info: { ...audio.info, pending: audio.blocking },
              paid: audio.paid,
              open: soundShown,
              popup: !soundInColumn,
              buttonId: soundButtonId,
              panelId: soundPanelId,
              onToggle: () => (soundShown ? closeSound() : openSound()),
            }}
          />
        ) : null
      }
      settingsTitle=""
      settingsOpen={false}
      onSettingsOpenChange={noop}
      settingsCollapsed
      feedScrollRef={feedScrollRef}
      labels={{
        history: t("merge.rail.title", { defaultValue: "Мои склейки" }),
        main: t("merge.name", { defaultValue: "Склейка видео" }),
      }}
      overlays={
        <>
          <MergeConfirmDialog
            open={m.confirm}
            count={m.edit.items.length}
            total={m.total}
            aspect={m.edit.aspect}
            fit={m.edit.fit}
            price={m.price}
            retentionDays={m.limits.retention_days}
            sound={audio.info}
            paid={audio.paid}
            voiceFrom={voiceFrom}
            onConfirm={() => actions.run(audio.flushSettings)}
            onClose={actions.cancelRun}
          />
          {!soundInColumn && (
            <BottomSheet
              open={soundShown}
              onClose={closeSound}
              title={t("merge.audio.title", { defaultValue: "Звук" })}
              size="full"
              className="vs-root"
              zIndex={1050}
              footer={
                <button type="button" onClick={closeSound} className={vx(VS_BTN_GHOST, "w-full")}>
                  {t("merge.dock.done", { defaultValue: "Готово" })}
                </button>
              }
            >
              <div className="pt-1">
                <MergeSoundPanel
                  audio={audio}
                  items={m.edit.items}
                  price={m.price}
                  variant="sheet"
                  headingId={soundHeading}
                  onClose={closeSound}
                  onAdd={addFromSound}
                />
              </div>
            </BottomSheet>
          )}
          <PaywallModal context={m.paywall} onClose={actions.closePaywall} onTopUp={actions.openTopup} />
          <TopUpModal open={m.topup} onClose={actions.closeTopup} returnTo={MERGE_PATH} />
        </>
      }
    />
  );
}

/** Гость: страница видна, но склеивать можно только своё — сначала вход. */
function GuestCard({ price, back }: { price: number; back: string }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <div className={vx(VS_CARD, "mx-auto flex max-w-xl flex-col items-start gap-3 p-5 sm:p-6")}>
      <span className="grid size-11 place-items-center rounded-2xl bg-accent/[0.1] text-xl text-vs-accent" aria-hidden="true">
        <FiScissors />
      </span>
      <h2 className={VS_H2}>{t("merge.guest.title", { defaultValue: "Войдите, чтобы склеить видео" })}</h2>
      <p className={VS_SUB}>
        {t("merge.guest.text", {
          defaultValue:
            "Склейка собирает в один ролик ваши готовые видео из видеостудии, мультстудии и чата, а также ваши собственные файлы.",
        })}{" "}
        {price > 0
          ? t("merge.guest.price", {
              defaultValue: "Стоит {{price}} кр — кредиты списываются только за готовый ролик.",
              price,
            })
          : t("merge.confirm.free", { defaultValue: "Склейка сейчас бесплатная." })}
      </p>
      <a href={signInHref(back)} onClick={() => rememberReturnPath(back)} className={vx(VS_BTN_GOLD, "mt-1")}>
        <FiLogIn aria-hidden="true" />
        {t("top.signin", { defaultValue: "Войти" })}
      </a>
    </div>
  );
}

/** Первый показ: те же две колонки, пока не ясно, что открыть. */
function WorkspaceSkeleton() {
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(300px,380px)_minmax(0,1fr)] lg:items-start xl:gap-8" aria-hidden="true">
      <div className="max-lg:hidden">
        <PickerSkeleton />
      </div>
      <TimelineSkeleton />
    </div>
  );
}
