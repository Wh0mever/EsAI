"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { IoClose, IoSearch } from "react-icons/io5";

type CatalogTask = {
  key: string;
  labelKey: string;
  labelDefault: string;
  promptKey: string;
  promptDefault: string;
};

type CatalogCategory = {
  key: string;
  icon: string;
  labelKey: string;
  labelDefault: string;
  tasks: CatalogTask[];
};

/**
 * TASK_CATALOG — полный каталог готовых задач для Bottom Sheet «Все
 * возможности» (просьба клиента, 24.07.2026): пользователи не знают,
 * что вообще умеет EsAI, и либо не начинают диалог, либо задают слишком
 * простые вопросы. 10 категорий, 54 задачи — точный список категорий и
 * названий задач продиктован клиентом дословно; тексты промптов (то, что
 * подставляется в поле ввода при клике) сгенерированы по 3 эталонным
 * примерам клиента и переведены на EN/KG (см. locales/{lang}/common.json,
 * ключ chat.catalog.categories).
 */
const TASK_CATALOG: CatalogCategory[] = [
  {
    key: "texts",
    icon: "✍️",
    labelKey: "chat.catalog.categories.texts.label",
    labelDefault: "Тексты",
    tasks: [
      { key: "article", labelKey: "chat.catalog.categories.texts.tasks.article.label", labelDefault: "Написать статью", promptKey: "chat.catalog.categories.texts.tasks.article.prompt", promptDefault: "Напиши статью на тему: " },
      { key: "letter", labelKey: "chat.catalog.categories.texts.tasks.letter.label", labelDefault: "Написать письмо", promptKey: "chat.catalog.categories.texts.tasks.letter.prompt", promptDefault: "Напиши письмо на тему: " },
      { key: "seoArticle", labelKey: "chat.catalog.categories.texts.tasks.seoArticle.label", labelDefault: "Написать SEO-статью", promptKey: "chat.catalog.categories.texts.tasks.seoArticle.prompt", promptDefault: "Напиши SEO-статью на тему: " },
      { key: "commercialProposal", labelKey: "chat.catalog.categories.texts.tasks.commercialProposal.label", labelDefault: "Написать коммерческое предложение", promptKey: "chat.catalog.categories.texts.tasks.commercialProposal.prompt", promptDefault: "Напиши коммерческое предложение на тему: " },
      { key: "instruction", labelKey: "chat.catalog.categories.texts.tasks.instruction.label", labelDefault: "Написать инструкцию", promptKey: "chat.catalog.categories.texts.tasks.instruction.prompt", promptDefault: "Напиши инструкцию на тему: " },
      { key: "adText", labelKey: "chat.catalog.categories.texts.tasks.adText.label", labelDefault: "Написать объявление", promptKey: "chat.catalog.categories.texts.tasks.adText.prompt", promptDefault: "Напиши объявление на тему: " },
      { key: "paraphrase", labelKey: "chat.catalog.categories.texts.tasks.paraphrase.label", labelDefault: "Перефразировать текст", promptKey: "chat.catalog.categories.texts.tasks.paraphrase.prompt", promptDefault: "Перефразируй этот текст: " },
      { key: "fixErrors", labelKey: "chat.catalog.categories.texts.tasks.fixErrors.label", labelDefault: "Исправить ошибки", promptKey: "chat.catalog.categories.texts.tasks.fixErrors.prompt", promptDefault: "Исправь ошибки в этом тексте: " },
      { key: "shorten", labelKey: "chat.catalog.categories.texts.tasks.shorten.label", labelDefault: "Сократить текст", promptKey: "chat.catalog.categories.texts.tasks.shorten.prompt", promptDefault: "Сократи этот текст: " },
      { key: "continueText", labelKey: "chat.catalog.categories.texts.tasks.continueText.label", labelDefault: "Продолжить текст", promptKey: "chat.catalog.categories.texts.tasks.continueText.prompt", promptDefault: "Продолжи этот текст: " },
    ],
  },
  {
    key: "documents",
    icon: "📄",
    labelKey: "chat.catalog.categories.documents.label",
    labelDefault: "Документы",
    tasks: [
      { key: "summarizeDoc", labelKey: "chat.catalog.categories.documents.tasks.summarizeDoc.label", labelDefault: "Пересказать документ", promptKey: "chat.catalog.categories.documents.tasks.summarizeDoc.prompt", promptDefault: "Кратко перескажи документ, который я прикреплю" },
      { key: "analyzeDoc", labelKey: "chat.catalog.categories.documents.tasks.analyzeDoc.label", labelDefault: "Проанализировать документ", promptKey: "chat.catalog.categories.documents.tasks.analyzeDoc.prompt", promptDefault: "Проанализируй документ, который я прикреплю" },
      { key: "reviewContract", labelKey: "chat.catalog.categories.documents.tasks.reviewContract.label", labelDefault: "Проверить договор", promptKey: "chat.catalog.categories.documents.tasks.reviewContract.prompt", promptDefault: "Проверь договор, который я прикреплю, на риски и подводные камни" },
      { key: "findErrorsDoc", labelKey: "chat.catalog.categories.documents.tasks.findErrorsDoc.label", labelDefault: "Найти ошибки", promptKey: "chat.catalog.categories.documents.tasks.findErrorsDoc.prompt", promptDefault: "Найди ошибки в документе, который я прикреплю" },
      { key: "highlightMain", labelKey: "chat.catalog.categories.documents.tasks.highlightMain.label", labelDefault: "Выделить главное", promptKey: "chat.catalog.categories.documents.tasks.highlightMain.prompt", promptDefault: "Выдели главное в документе, который я прикреплю" },
      { key: "explainSimply", labelKey: "chat.catalog.categories.documents.tasks.explainSimply.label", labelDefault: "Объяснить простыми словами", promptKey: "chat.catalog.categories.documents.tasks.explainSimply.prompt", promptDefault: "Объясни простыми словами документ, который я прикреплю" },
    ],
  },
  {
    key: "social",
    icon: "📱",
    labelKey: "chat.catalog.categories.social.label",
    labelDefault: "Социальные сети",
    tasks: [
      { key: "createPost", labelKey: "chat.catalog.categories.social.tasks.createPost.label", labelDefault: "Создать пост", promptKey: "chat.catalog.categories.social.tasks.createPost.prompt", promptDefault: "Напиши пост для соцсетей на тему: " },
      { key: "adCopy", labelKey: "chat.catalog.categories.social.tasks.adCopy.label", labelDefault: "Создать рекламный текст", promptKey: "chat.catalog.categories.social.tasks.adCopy.prompt", promptDefault: "Напиши рекламный текст для " },
      { key: "productDescription", labelKey: "chat.catalog.categories.social.tasks.productDescription.label", labelDefault: "Написать описание товара", promptKey: "chat.catalog.categories.social.tasks.productDescription.prompt", promptDefault: "Напиши продающее описание товара: " },
      { key: "contentPlan", labelKey: "chat.catalog.categories.social.tasks.contentPlan.label", labelDefault: "Создать контент-план", promptKey: "chat.catalog.categories.social.tasks.contentPlan.prompt", promptDefault: "Создай контент-план для соцсетей на тему: " },
      { key: "reelsIdeas", labelKey: "chat.catalog.categories.social.tasks.reelsIdeas.label", labelDefault: "Придумать идеи для Reels", promptKey: "chat.catalog.categories.social.tasks.reelsIdeas.prompt", promptDefault: "Придумай идеи для Reels на тему: " },
      { key: "catchyHeadline", labelKey: "chat.catalog.categories.social.tasks.catchyHeadline.label", labelDefault: "Написать цепляющий заголовок", promptKey: "chat.catalog.categories.social.tasks.catchyHeadline.prompt", promptDefault: "Придумай цепляющий заголовок на тему: " },
    ],
  },
  {
    key: "images",
    icon: "🎨",
    labelKey: "chat.catalog.categories.images.label",
    labelDefault: "Изображения",
    tasks: [
      { key: "createImage", labelKey: "chat.catalog.categories.images.tasks.createImage.label", labelDefault: "Создать изображение", promptKey: "chat.catalog.categories.images.tasks.createImage.prompt", promptDefault: "Создай реалистичное изображение: " },
      { key: "createLogo", labelKey: "chat.catalog.categories.images.tasks.createLogo.label", labelDefault: "Создать логотип", promptKey: "chat.catalog.categories.images.tasks.createLogo.prompt", promptDefault: "Создай логотип для компании: " },
      { key: "createBanner", labelKey: "chat.catalog.categories.images.tasks.createBanner.label", labelDefault: "Создать баннер", promptKey: "chat.catalog.categories.images.tasks.createBanner.prompt", promptDefault: "Создай баннер на тему: " },
      { key: "createCover", labelKey: "chat.catalog.categories.images.tasks.createCover.label", labelDefault: "Создать обложку", promptKey: "chat.catalog.categories.images.tasks.createCover.prompt", promptDefault: "Создай обложку на тему: " },
      { key: "enhancePhoto", labelKey: "chat.catalog.categories.images.tasks.enhancePhoto.label", labelDefault: "Улучшить фото", promptKey: "chat.catalog.categories.images.tasks.enhancePhoto.prompt", promptDefault: "Улучши качество фото, которое я прикреплю" },
      { key: "removeBackground", labelKey: "chat.catalog.categories.images.tasks.removeBackground.label", labelDefault: "Удалить фон", promptKey: "chat.catalog.categories.images.tasks.removeBackground.prompt", promptDefault: "Удали фон с фото, которое я прикреплю" },
    ],
  },
  {
    key: "video",
    icon: "🎥",
    labelKey: "chat.catalog.categories.video.label",
    labelDefault: "Видео",
    tasks: [
      { key: "createVideo", labelKey: "chat.catalog.categories.video.tasks.createVideo.label", labelDefault: "Создать видео", promptKey: "chat.catalog.categories.video.tasks.createVideo.prompt", promptDefault: "Создай короткое видео на тему: " },
      { key: "writeScript", labelKey: "chat.catalog.categories.video.tasks.writeScript.label", labelDefault: "Написать сценарий", promptKey: "chat.catalog.categories.video.tasks.writeScript.prompt", promptDefault: "Напиши сценарий видео на тему: " },
      { key: "storyboard", labelKey: "chat.catalog.categories.video.tasks.storyboard.label", labelDefault: "Создать раскадровку", promptKey: "chat.catalog.categories.video.tasks.storyboard.prompt", promptDefault: "Создай раскадровку для видео на тему: " },
      { key: "shortsIdeas", labelKey: "chat.catalog.categories.video.tasks.shortsIdeas.label", labelDefault: "Придумать идеи для Shorts", promptKey: "chat.catalog.categories.video.tasks.shortsIdeas.prompt", promptDefault: "Придумай идеи для Shorts на тему: " },
    ],
  },
  {
    key: "code",
    icon: "💻",
    labelKey: "chat.catalog.categories.code.label",
    labelDefault: "Программирование",
    tasks: [
      { key: "writeCode", labelKey: "chat.catalog.categories.code.tasks.writeCode.label", labelDefault: "Написать код", promptKey: "chat.catalog.categories.code.tasks.writeCode.prompt", promptDefault: "Напиши код на Python, который " },
      { key: "fixBug", labelKey: "chat.catalog.categories.code.tasks.fixBug.label", labelDefault: "Исправить ошибку", promptKey: "chat.catalog.categories.code.tasks.fixBug.prompt", promptDefault: "Исправь ошибку в этом коде: " },
      { key: "explainCode", labelKey: "chat.catalog.categories.code.tasks.explainCode.label", labelDefault: "Объяснить код", promptKey: "chat.catalog.categories.code.tasks.explainCode.prompt", promptDefault: "Объясни, что делает этот код: " },
      { key: "optimizeCode", labelKey: "chat.catalog.categories.code.tasks.optimizeCode.label", labelDefault: "Оптимизировать код", promptKey: "chat.catalog.categories.code.tasks.optimizeCode.prompt", promptDefault: "Оптимизируй и ускорь этот код: " },
      { key: "sqlQuery", labelKey: "chat.catalog.categories.code.tasks.sqlQuery.label", labelDefault: "Написать SQL-запрос", promptKey: "chat.catalog.categories.code.tasks.sqlQuery.prompt", promptDefault: "Напиши SQL-запрос, который " },
    ],
  },
  {
    key: "work",
    icon: "📊",
    labelKey: "chat.catalog.categories.work.label",
    labelDefault: "Работа",
    tasks: [
      { key: "presentation", labelKey: "chat.catalog.categories.work.tasks.presentation.label", labelDefault: "Создать презентацию", promptKey: "chat.catalog.categories.work.tasks.presentation.prompt", promptDefault: "Создай структуру презентации по теме: " },
      { key: "table", labelKey: "chat.catalog.categories.work.tasks.table.label", labelDefault: "Создать таблицу", promptKey: "chat.catalog.categories.work.tasks.table.prompt", promptDefault: "Создай таблицу на тему: " },
      { key: "resume", labelKey: "chat.catalog.categories.work.tasks.resume.label", labelDefault: "Составить резюме", promptKey: "chat.catalog.categories.work.tasks.resume.prompt", promptDefault: "Составь резюме на позицию: " },
      { key: "coverLetter", labelKey: "chat.catalog.categories.work.tasks.coverLetter.label", labelDefault: "Написать сопроводительное письмо", promptKey: "chat.catalog.categories.work.tasks.coverLetter.prompt", promptDefault: "Напиши сопроводительное письмо на вакансию: " },
      { key: "interviewPrep", labelKey: "chat.catalog.categories.work.tasks.interviewPrep.label", labelDefault: "Подготовиться к собеседованию", promptKey: "chat.catalog.categories.work.tasks.interviewPrep.prompt", promptDefault: "Помоги подготовиться к собеседованию на позицию: " },
    ],
  },
  {
    key: "business",
    icon: "💡",
    labelKey: "chat.catalog.categories.business.label",
    labelDefault: "Бизнес",
    tasks: [
      { key: "businessIdea", labelKey: "chat.catalog.categories.business.tasks.businessIdea.label", labelDefault: "Придумать бизнес-идею", promptKey: "chat.catalog.categories.business.tasks.businessIdea.prompt", promptDefault: "Предложи бизнес-идею для " },
      { key: "businessPlan", labelKey: "chat.catalog.categories.business.tasks.businessPlan.label", labelDefault: "Написать бизнес-план", promptKey: "chat.catalog.categories.business.tasks.businessPlan.prompt", promptDefault: "Составь бизнес-план для проекта: " },
      { key: "competitorAnalysis", labelKey: "chat.catalog.categories.business.tasks.competitorAnalysis.label", labelDefault: "Проанализировать конкурентов", promptKey: "chat.catalog.categories.business.tasks.competitorAnalysis.prompt", promptDefault: "Проанализируй конкурентов в сфере: " },
      { key: "marketingPlan", labelKey: "chat.catalog.categories.business.tasks.marketingPlan.label", labelDefault: "Создать маркетинговый план", promptKey: "chat.catalog.categories.business.tasks.marketingPlan.prompt", promptDefault: "Создай маркетинговый план для продукта: " },
      { key: "projectEconomics", labelKey: "chat.catalog.categories.business.tasks.projectEconomics.label", labelDefault: "Рассчитать экономику проекта", promptKey: "chat.catalog.categories.business.tasks.projectEconomics.prompt", promptDefault: "Рассчитай экономику проекта: " },
    ],
  },
  {
    key: "translate",
    icon: "🌐",
    labelKey: "chat.catalog.categories.translate.label",
    labelDefault: "Перевод",
    tasks: [
      { key: "translateText", labelKey: "chat.catalog.categories.translate.tasks.translateText.label", labelDefault: "Перевести текст", promptKey: "chat.catalog.categories.translate.tasks.translateText.prompt", promptDefault: "Переведи этот текст: " },
      { key: "translateDocument", labelKey: "chat.catalog.categories.translate.tasks.translateDocument.label", labelDefault: "Перевести документ", promptKey: "chat.catalog.categories.translate.tasks.translateDocument.prompt", promptDefault: "Переведи документ, который я прикреплю" },
      { key: "translateWebsite", labelKey: "chat.catalog.categories.translate.tasks.translateWebsite.label", labelDefault: "Перевести сайт", promptKey: "chat.catalog.categories.translate.tasks.translateWebsite.prompt", promptDefault: "Переведи сайт по этой ссылке: " },
    ],
  },
  {
    key: "study",
    icon: "📚",
    labelKey: "chat.catalog.categories.study.label",
    labelDefault: "Учёба",
    tasks: [
      { key: "solveProblem", labelKey: "chat.catalog.categories.study.tasks.solveProblem.label", labelDefault: "Решить задачу", promptKey: "chat.catalog.categories.study.tasks.solveProblem.prompt", promptDefault: "Реши подробно эту задачу: " },
      { key: "explainTopic", labelKey: "chat.catalog.categories.study.tasks.explainTopic.label", labelDefault: "Объяснить тему", promptKey: "chat.catalog.categories.study.tasks.explainTopic.prompt", promptDefault: "Объясни простыми словами тему: " },
      { key: "examPrep", labelKey: "chat.catalog.categories.study.tasks.examPrep.label", labelDefault: "Подготовиться к экзамену", promptKey: "chat.catalog.categories.study.tasks.examPrep.prompt", promptDefault: "Помоги подготовиться к экзамену по теме: " },
      { key: "notes", labelKey: "chat.catalog.categories.study.tasks.notes.label", labelDefault: "Создать конспект", promptKey: "chat.catalog.categories.study.tasks.notes.prompt", promptDefault: "Составь краткий конспект по теме: " },
    ],
  },
];

type Props = {
  open: boolean;
  onClose: () => void;
  onSelectPrompt: (prompt: string) => void;
};

/**
 * TaskCatalogSheet — Bottom Sheet «Все возможности» на стартовом экране
 * чата (кнопка рядом с быстрыми промптами, см. StartScreen.tsx). Просьба
 * клиента (24.07.2026): многие не знают, что вообще умеет EsAI —
 * каталог из 10 категорий и ~54 готовых задач должен наглядно показать
 * возможности и снизить порог первого сообщения.
 *
 * Клик по задаче: закрывает шторку, подставляет промпт в поле ввода
 * (onSelectPrompt → ChatWorkspace.onUsePrompt → setInput + focusSignal,
 * см. ChatComposer.tsx) — курсор сразу в конце, пользователь дописывает
 * детали и жмёт «Отправить» сам (не отправляем автоматически).
 */
export default function TaskCatalogSheet({ open, onClose, onSelectPrompt }: Props) {
  const { t } = useTranslation("common");
  const [query, setQuery] = useState("");
  const [visible, setVisible] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // Плавный выезд снизу: монтируем сразу со сдвигом вниз, на следующем
  // кадре включаем translate-y-0 — иначе transition не срабатывает
  // (класс уже был бы "конечным" на первом же рендере).
  useEffect(() => {
    if (!open) {
      setVisible(false);
      return;
    }
    const raf = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(raf);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow || "";
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  const normalizedQuery = query.trim().toLowerCase();

  const filteredCategories = useMemo(() => {
    if (!normalizedQuery) return TASK_CATALOG;
    return TASK_CATALOG.map((cat) => ({
      ...cat,
      tasks: cat.tasks.filter((task) =>
        t(task.labelKey, { defaultValue: task.labelDefault }).toLowerCase().includes(normalizedQuery)
      ),
    })).filter((cat) => cat.tasks.length > 0);
  }, [normalizedQuery, t]);

  const handleSelect = (task: CatalogTask) => {
    onSelectPrompt(t(task.promptKey, { defaultValue: task.promptDefault }));
    onClose();
  };

  if (typeof window === "undefined" || !open) return null;

  return createPortal(
    <div
      className={
        "fixed inset-0 z-[1200] flex items-end justify-center bg-black/70 transition-opacity duration-300 " +
        (visible ? "opacity-100" : "opacity-0")
      }
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("chat.catalog.title", { defaultValue: "Выберите задачу" })}
    >
      <div
        className={
          "w-full max-w-2xl bg-surface rounded-t-2xl border border-border border-b-0 flex flex-col " +
          "max-h-[88dvh] transition-transform duration-300 ease-out " +
          (visible ? "translate-y-0" : "translate-y-full")
        }
        onClick={(e) => e.stopPropagation()}
      >
        {/* Ручка + кнопка закрытия */}
        <div className="relative shrink-0 pt-2.5 pb-1 px-4">
          <div className="mx-auto h-1 w-10 rounded-full bg-border" />
          <button
            type="button"
            onClick={onClose}
            aria-label={t("common.close", { defaultValue: "Закрыть" })}
            className="absolute right-3 top-2 w-8 h-8 grid place-items-center rounded-lg text-muted hover:text-foreground hover:bg-surface-2 cursor-pointer"
          >
            <IoClose className="text-xl" />
          </button>
        </div>

        {/* Поиск задачи */}
        <div className="shrink-0 px-4 pt-1 pb-2">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-2 px-3 py-2.5">
            <IoSearch className="text-muted shrink-0" />
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("chat.catalog.search_placeholder", { defaultValue: "Поиск задачи..." })}
              className="w-full bg-transparent outline-none text-sm text-foreground placeholder:text-muted"
            />
          </div>
          <p className="mt-2.5 text-sm font-semibold text-foreground">
            {t("chat.catalog.title", { defaultValue: "Выберите задачу" })}
          </p>
        </div>

        {/* Категории и задачи */}
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          {filteredCategories.length === 0 && (
            <p className="text-center text-sm text-muted py-8">
              {t("chat.catalog.no_results", { defaultValue: "Ничего не найдено" })}
            </p>
          )}
          {filteredCategories.map((cat) => (
            <div key={cat.key} className="mb-4">
              <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground mb-2">
                <span aria-hidden>{cat.icon}</span>
                {t(cat.labelKey, { defaultValue: cat.labelDefault })}
              </h3>
              <div className="flex flex-wrap gap-2">
                {cat.tasks.map((task) => (
                  <button
                    key={task.key}
                    type="button"
                    onClick={() => handleSelect(task)}
                    className="rounded-full border border-border bg-surface-2 hover:border-accent/60 hover:text-accent-strong text-foreground text-xs sm:text-sm font-medium px-3 py-1.5 cursor-pointer transition-colors"
                  >
                    {t(task.labelKey, { defaultValue: task.labelDefault })}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>,
    document.body
  );
}
