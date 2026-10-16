"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import VStudioShell, { useVsBreakpoint } from "@/components/vstudio/VStudioShell";
import { useVisualViewport } from "@/components/vstudio/hooks/useVisualViewport";
import { StudioAuthDialog, StudioPaywallDialog } from "./StudioDialogs";
import CartoonDock from "./CartoonDock";
import CartoonIntro from "./CartoonIntro";
import CartoonTopBar, { CartoonHeader, ErrorBanner } from "./CartoonTopBar";
import HeroStrip from "./HeroStrip";
import MoviesRail from "./MoviesRail";
import ResultPanel from "./ResultPanel";
import SceneAudioDialog from "./SceneAudioDialog";
import SceneLibrary from "./SceneLibrary";
import TimelinePanel from "./TimelinePanel";
import VoiceAllDialog from "./VoiceAllDialog";
import { useCartoonStudio } from "./useCartoonStudio";

/**
 * CartoonStudio — студия мультфильмов: персонаж → сцены → таймлайн → готовый
 * ролик.
 *
 * Замысел клиента: человек не пишет промпты. Он берёт героя, набирает готовые
 * сцены и жмёт «Собрать мультфильм». Модель, качество и длительность он может
 * сменить внизу, в доке (по умолчанию — самая дешёвая сцена: Seedance Mini в
 * 480p); остальное спрятано в пресетах и правится в админке.
 *
 * Каркас — тот же, что у видеостудии (VStudioShell): слева мои мультфильмы
 * (колонка, на узком — шторка), сверху строка с названием и балансом, в
 * середине прокручиваемая лента шагов, внизу док. Состояние, запросы и деньги
 * живут в useCartoonStudio; здесь только раскладка по компонентам.
 *
 * variant="tg" — Mini App в Telegram: всегда одна колонка, как на телефоне, и
 * без ссылок с сайта; шторка со списком мультфильмов остаётся.
 */
const noop = () => {};

/** Поля, в которых печатают: пока фокус в одном из них, на телефоне дока нет. */
const TEXT_FIELD =
  'textarea, input:not([type="checkbox"]):not([type="radio"]):not([type="file"]):not([type="range"]):not([type="button"]):not([type="submit"]), [contenteditable="true"]';

const isTextField = (el: Element | null): boolean => el instanceof HTMLElement && el.matches(TEXT_FIELD);

/**
 * Фокус — на заголовок секции, к которой прокрутили («Мои герои», мультфильм
 * из списка, «К ленте сцен»): иначе шторка вернула бы его на ☰, и с клавиатуры
 * пришлось бы идти от верха ленты. Через два кадра — после того, как шторка
 * вернёт свой; страницу не двигает (её везёт прокрутка).
 */
function focusHeading(ref: RefObject<HTMLElement | null>) {
  window.requestAnimationFrame(() =>
    window.requestAnimationFrame(() => ref.current?.querySelector<HTMLElement>("h2[tabindex]")?.focus({ preventScroll: true })),
  );
}

export default function CartoonStudio({ variant = "site" }: { variant?: "site" | "tg" }) {
  const { t } = useTranslation("common");
  const s = useCartoonStudio();
  const { actions } = s;
  const measured = useVsBreakpoint();
  const breakpoint = variant === "tg" ? "mobile" : measured;
  // Высота оболочки — видимая часть окна: на телефоне с клавиатурой док остаётся над ней.
  useVisualViewport({ cssVars: true });
  const feedScrollRef = useRef<HTMLDivElement | null>(null);
  const [railOpen, setRailOpen] = useState(false);
  // Печатают в ленте (реплика, своя сцена, описание героя). На телефоне клавиатура
  // и так забирает полэкрана — док на это время убираем, ленте остаётся место.
  const [typing, setTyping] = useState(false);
  const home = variant === "tg" ? "/tg/studio" : "/studio";

  useEffect(() => {
    const feed = feedScrollRef.current;
    if (!feed) return;
    let timer = 0;
    const onIn = (e: FocusEvent) => {
      if (!isTextField(e.target as Element | null)) return;
      window.clearTimeout(timer);
      setTyping(true);
    };
    // Док возвращается с паузой: нажатие на кнопку рядом с полем успевает дойти до
    // неё, а не до дока, который встал бы на её место.
    const onOut = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const active = document.activeElement;
        setTyping(isTextField(active) && feed.contains(active));
      }, 150);
    };
    feed.addEventListener("focusin", onIn);
    feed.addEventListener("focusout", onOut);
    return () => {
      window.clearTimeout(timer);
      feed.removeEventListener("focusin", onIn);
      feed.removeEventListener("focusout", onOut);
    };
  }, []);

  // Mini App: прокручивается лента внутри оболочки, а не сама страница, и Telegram
  // принимал бы прокрутку ленты вверх за свайп «свернуть». Уходим — возвращаем свайп.
  useEffect(() => {
    if (variant !== "tg") return;
    const app = window.Telegram?.WebApp;
    app?.disableVerticalSwipes?.();
    return () => app?.enableVerticalSwipes?.();
  }, [variant]);

  // В общем списке открытый мультфильм может отставать от себя же: опрос и
  // правки обновляют сначала его — в колонке показываем свежую копию.
  const open = s.project;
  const movies = open ? s.movies.map((m) => (m.id === open.id ? open : m)) : s.movies;

  const toHeroes = () => {
    actions.scrollToHeroes();
    focusHeading(s.refs.heroes);
  };

  const toTimeline = () => {
    actions.scrollToTimeline();
    focusHeading(s.refs.timeline);
  };

  const openMovie = (id: number) => {
    void actions.openProject(id);
    // Открыли мультфильм из списка — показываем его ленту: на прежнем месте
    // сменились бы только цифры, и было бы непонятно, что произошло.
    window.requestAnimationFrame(toTimeline);
  };

  const newMovie = () => {
    actions.startNewMovie();
    // Новый мультфильм начинается с героя и сцен — с начала ленты, как «Новая генерация» видеостудии.
    if (feedScrollRef.current) feedScrollRef.current.scrollTop = 0;
  };

  const top = {
    loading: s.loading,
    authed: s.authed,
    balance: s.balance,
    balanceFailed: s.balanceFailed,
    project: s.project,
    back: home,
    onRename: (v: string) => void actions.renameMovie(v),
  };

  return (
    <VStudioShell
      breakpoint={breakpoint}
      // Лента во всю ширину колонки: поля и ширину секции задают себе сами (VS_SECTION).
      home
      rail={(v) => (
        <MoviesRail
          variant={v}
          host={variant}
          loading={s.loading}
          authed={s.authed}
          movies={movies}
          currentId={s.project?.id ?? null}
          balance={s.balance}
          balanceFailed={s.balanceFailed}
          onOpen={openMovie}
          onNew={newMovie}
          onRename={(value) => void actions.renameMovie(value)}
          onHeroes={toHeroes}
          onExpand={() => setRailOpen(true)}
          onNavigate={() => setRailOpen(false)}
        />
      )}
      railOpen={railOpen}
      onRailOpenChange={setRailOpen}
      header={<CartoonHeader {...top} />}
      topBar={<CartoonTopBar {...top} onMenu={() => setRailOpen(true)} />}
      banner={s.error ? <ErrorBanner message={s.error} onClose={actions.clearError} /> : null}
      feed={
        // pb-6 к отступу оболочки (pb-10): вместе не меньше затухания над доком (56 px),
        // и кнопки последней карточки не уходят под него.
        <div className="flex flex-col pb-6">
          <CartoonIntro host={variant} />

          <HeroStrip
            loading={s.loading}
            authed={s.authed}
            heroes={s.heroes.list}
            cast={s.heroes.cast}
            selected={s.heroes.selected}
            needHero={s.heroes.needHero}
            audience={s.heroes.audience}
            showAudience={s.heroes.showAudience}
            balance={s.balance}
            sectionRef={s.refs.heroes}
            onAudience={actions.pickAudience}
            onPick={actions.pickHero}
            onCreated={actions.heroCreated}
            onDeleted={actions.heroDeleted}
            onNeedAuth={() => actions.openAuth("character")}
            onNeedCredits={(required, bal) => actions.openPaywall({ required, balance: bal, kind: "character" })}
          />

          {/* Сцены показываем сразу, не дожидаясь выбора героя: клиент попросил,
              чтобы витрину было видно с порога — ради неё в студию и заходят. */}
          <SceneLibrary
            loading={s.loading}
            authed={s.authed}
            presets={s.library.presets}
            restCount={s.library.restCount}
            categories={s.library.categories}
            hasPopular={s.library.hasPopular}
            hasPicks={s.library.hasPicks}
            activeCat={s.library.activeCat}
            audience={s.heroes.audience}
            selected={s.heroes.selected}
            cast={s.heroes.cast}
            frames={s.library.frames}
            heroVideos={s.library.heroVideos}
            adding={s.library.adding}
            tryingOn={s.library.tryingOn}
            customText={s.library.customText}
            cardPrice={s.library.cardPrice}
            onCategory={actions.pickCategory}
            onMore={actions.showMore}
            onAdd={(p) => void actions.addScene(p)}
            onTryOn={(p) => void actions.tryOnScene(p)}
            onPickHero={actions.pickHero}
            onHeroes={toHeroes}
            onCustomText={actions.setCustomText}
            onAddCustom={() => void actions.addCustomScene()}
          />

          <TimelinePanel
            loading={s.loading}
            authed={s.authed}
            show={s.timeline.show}
            project={s.project}
            scenes={s.timeline.scenes}
            characters={s.timeline.characters}
            busyIds={s.timeline.busyIds}
            repricing={s.timeline.repricing}
            framingId={s.timeline.framingId}
            frameCredits={s.timeline.frameCredits}
            tryingOn={s.library.tryingOn}
            notes={s.timeline.notes}
            handlers={s.timeline.handlers}
            aspect={s.aspect}
            readyCount={s.timeline.readyCount}
            drafts={s.timeline.drafts}
            working={s.timeline.working}
            voicingNow={s.timeline.voicingNow}
            total={s.timeline.total}
            audioEnabled={s.timeline.audioEnabled}
            planning={s.timeline.planning}
            assembling={s.timeline.assembling}
            sectionRef={s.refs.timeline}
            onRename={(v) => void actions.renameMovie(v)}
            onNewMovie={newMovie}
            onAssemble={() => void actions.assemble()}
            onVoiceAll={() => void actions.planVoiceAll()}
            onGuestRender={() => actions.guestRender("cta")}
          />

          <ResultPanel
            project={s.project}
            shareUrl={s.result.shareUrl}
            readyCount={s.timeline.readyCount}
            assembling={s.timeline.assembling}
            onAssemble={() => void actions.assemble()}
            onNewMovie={newMovie}
          />
        </div>
      }
      // Док: модель, качество, длительность, формат, сумма к съёмке и главная кнопка.
      // Меняет только сцены, которые ещё не снимаются. Пока на телефоне печатают в
      // ленте, дока нет (typing).
      composer={
        typing && breakpoint === "mobile" ? null : (
          <CartoonDock
            models={s.dock.models}
            modelsError={s.dock.modelsError}
            onRetryModels={actions.retryModels}
            value={s.dock.value}
            onModel={actions.pickDockModel}
            onResolution={actions.pickDockResolution}
            onDuration={actions.pickDockDuration}
            onAspect={(v) => void actions.pickAspect(v)}
            notices={s.dock.notices}
            onDismissNotices={actions.dismissNotices}
            warning={s.dock.warning}
            total={s.dock.total}
            hasShot={s.dock.hasShot}
            frameCredits={s.dock.frameCredits}
            saving={s.dock.saving}
            // Пока студия грузится, мультфильма и черновика ещё нет: выбор в доке лёг бы
            // в пустой черновик гостя поверх сохранённого и стёр бы его сцены.
            disabled={s.loading}
            error={s.dock.error}
            onDismissError={actions.dismissDockError}
            primary={s.dock.primary}
            onTotal={toTimeline}
          />
        )
      }
      // Параметров отдельной панелью у мультстудии нет: они в доке.
      settingsTitle=""
      settingsOpen={false}
      onSettingsOpenChange={noop}
      settingsCollapsed
      feedScrollRef={feedScrollRef}
      labels={{
        history: t("studio_ui.my_movies"),
        main: t("studio_ui.shell_name", { defaultValue: "Мультстудия" }),
      }}
      overlays={
        <>
          <StudioPaywallDialog
            open={Boolean(s.dialogs.shortfall)}
            required={s.dialogs.shortfall?.required ?? 0}
            balance={s.dialogs.shortfall?.balance ?? 0}
            kind={s.dialogs.shortfall?.kind ?? "scene"}
            onClose={actions.closePaywall}
          />
          <StudioAuthDialog
            open={Boolean(s.dialogs.authFor)}
            reason={s.dialogs.authFor ?? "render"}
            onClose={actions.closeAuth}
          />
          <SceneAudioDialog
            scene={s.dialogs.audioScene}
            config={s.dialogs.audioConfig}
            characters={s.dialogs.audioCharacters}
            onClose={actions.closeAudio}
            onChanged={actions.audioChanged}
            onNeedCredits={(required, bal) => actions.openPaywall({ required, balance: bal, kind: "audio" })}
          />
          <VoiceAllDialog
            open={Boolean(s.dialogs.voicePlan)}
            plan={s.dialogs.voicePlan}
            config={s.dialogs.audioConfig}
            projectId={s.project?.id ?? null}
            onClose={actions.closeVoicePlan}
            onStarted={actions.voiceStarted}
            onNeedCredits={(required, bal) => actions.openPaywall({ required, balance: bal, kind: "audio" })}
          />
        </>
      }
    />
  );
}
