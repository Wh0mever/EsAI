"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { fetchData } from "@/tools/fetchData";
import { FiExternalLink, FiTrash2 } from "react-icons/fi";

type BlogPost = {
  id: number;
  slug: string;
  title_ru: string;
  title_en: string;
  title_kg: string;
  content_ru: string;
  content_en: string;
  content_kg: string;
  excerpt: string;
  meta_title: string;
  meta_description: string;
  author: string;
  is_published: boolean;
  published_at: string | null;
};

const INPUT =
  "rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none";

export default function AdminBlogEditPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id ?? "new";
  const isNew = id === "new";

  const [loading, setLoading] = useState(!isNew);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [titleRu, setTitleRu] = useState("");
  const [slug, setSlug] = useState("");
  const [contentRu, setContentRu] = useState("");
  const [excerpt, setExcerpt] = useState("");
  const [metaTitle, setMetaTitle] = useState("");
  const [metaDescription, setMetaDescription] = useState("");
  const [isPublished, setIsPublished] = useState(false);

  useEffect(() => {
    if (isNew) return;
    let alive = true;
    (async () => {
      const res = await fetchData<BlogPost>(`manage/blog/${id}/`, "GET", null, true);
      if (!alive) return;
      if (res.ok && res.data) {
        const p = res.data;
        setTitleRu(p.title_ru || "");
        setSlug(p.slug || "");
        setContentRu(p.content_ru || "");
        setExcerpt(p.excerpt || "");
        setMetaTitle(p.meta_title || "");
        setMetaDescription(p.meta_description || "");
        setIsPublished(Boolean(p.is_published));
      } else {
        setError(res.error || "Статья не найдена");
      }
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [id, isNew]);

  const save = async () => {
    if (!titleRu.trim() || !slug.trim()) {
      setSaveError("Заполните заголовок и URL статьи");
      return;
    }
    setSaving(true);
    setSaveError(null);
    const payload = {
      slug: slug.trim(),
      title_ru: titleRu.trim(),
      content_ru: contentRu,
      excerpt,
      meta_title: metaTitle,
      meta_description: metaDescription,
      is_published: isPublished,
    };
    const res = isNew
      ? await fetchData<BlogPost>("manage/blog/", "POST", payload, true)
      : await fetchData<BlogPost>(`manage/blog/${id}/`, "PATCH", payload, true);
    setSaving(false);
    if (res.ok) {
      router.push("/admin-new/blog");
    } else {
      setSaveError(res.error || "Не удалось сохранить статью");
    }
  };

  const remove = async () => {
    if (isNew) return;
    if (!window.confirm("Удалить статью безвозвратно?")) return;
    setDeleting(true);
    const res = await fetchData(`manage/blog/${id}/`, "DELETE", null, true);
    setDeleting(false);
    if (res.ok) {
      router.push("/admin-new/blog");
    } else {
      setSaveError(res.error || "Не удалось удалить статью");
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-64 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-96 animate-pulse rounded-2xl bg-surface-2" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
        {error}{" "}
        <Link href="/admin-new/blog" className="text-accent hover:underline">
          ← К списку статей
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">
          {isNew ? "Новая статья" : "Редактирование статьи"}
        </h1>
        {!isNew && isPublished && slug && (
          <a
            href={`/blog/${slug}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline"
          >
            <FiExternalLink className="h-4 w-4" />
            Открыть на сайте
          </a>
        )}
      </div>

      <div className="space-y-4 rounded-2xl border border-border bg-surface p-5 md:p-6">
        <label className="block">
          <span className="mb-1 block text-sm text-muted">Заголовок</span>
          <input
            type="text"
            className={`${INPUT} w-full`}
            value={titleRu}
            onChange={(e) => setTitleRu(e.target.value)}
            placeholder="Например: Как выбрать AI-модель для работы"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-sm text-muted">
            URL (латиницей, через дефис)
          </span>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-2">/blog/</span>
            <input
              type="text"
              className={`${INPUT} w-full font-mono`}
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="kak-vybrat-ai-model"
            />
          </div>
        </label>

        <label className="block">
          <span className="mb-1 block text-sm text-muted">Текст статьи</span>
          <textarea
            rows={20}
            className={`${INPUT} w-full font-mono leading-relaxed`}
            value={contentRu}
            onChange={(e) => setContentRu(e.target.value)}
            placeholder={"## Заголовок раздела\n\nОбычный текст…"}
          />
          <span className="mt-1 block text-xs text-muted-2">
            Markdown: ## заголовки, **жирный**, списки „- "
          </span>
        </label>

        <label className="block">
          <span className="mb-1 block text-sm text-muted">
            Краткое описание (анонс в списке статей)
          </span>
          <textarea
            rows={3}
            className={`${INPUT} w-full`}
            value={excerpt}
            onChange={(e) => setExcerpt(e.target.value)}
          />
        </label>

        <details className="rounded-xl border border-border bg-surface-2/50 p-4">
          <summary className="cursor-pointer text-sm font-medium text-muted">
            SEO-настройки (необязательно)
          </summary>
          <div className="mt-4 space-y-4">
            <label className="block">
              <span className="mb-1 block text-sm text-muted">SEO title</span>
              <input
                type="text"
                className={`${INPUT} w-full`}
                value={metaTitle}
                onChange={(e) => setMetaTitle(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm text-muted">SEO description</span>
              <textarea
                rows={2}
                className={`${INPUT} w-full`}
                value={metaDescription}
                onChange={(e) => setMetaDescription(e.target.value)}
              />
            </label>
          </div>
        </details>

        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 accent-accent"
            checked={isPublished}
            onChange={(e) => setIsPublished(e.target.checked)}
          />
          Опубликована (видна на сайте)
        </label>
      </div>

      {saveError && <p className="text-sm text-rose-400">{saveError}</p>}

      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={save}
          disabled={saving}
          className="rounded-xl bg-accent px-6 py-2.5 text-sm font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Сохранение…" : "Сохранить"}
        </button>
        <Link
          href="/admin-new/blog"
          className="rounded-xl border border-border px-5 py-2.5 text-sm text-muted transition-colors hover:text-foreground"
        >
          Отмена
        </Link>
        {!isNew && (
          <button
            onClick={remove}
            disabled={deleting}
            className="ml-auto inline-flex items-center gap-1.5 rounded-xl border border-rose-400/30 px-4 py-2.5 text-sm text-rose-400 transition-colors hover:bg-rose-400/10 disabled:opacity-50"
          >
            <FiTrash2 className="h-4 w-4" />
            {deleting ? "Удаление…" : "Удалить"}
          </button>
        )}
      </div>
    </div>
  );
}
