"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchData } from "@/tools/fetchData";
import { FiPlus } from "react-icons/fi";

type BlogItem = {
  id: number;
  slug: string;
  title_ru: string;
  is_published: boolean;
  published_at: string | null;
  created_at: string;
};

const fmtDate = (s: string | null) => {
  if (!s) return "—";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
};

export default function AdminBlogPage() {
  const router = useRouter();
  const [posts, setPosts] = useState<BlogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<BlogItem[]>("manage/blog/", "GET", null, true);
      if (!alive) return;
      if (res.ok && Array.isArray(res.data)) setPosts(res.data);
      else setError(res.error || "Не удалось загрузить статьи");
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-40 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-96 animate-pulse rounded-2xl bg-surface-2" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Блог</h1>
          <p className="mt-1 text-sm text-muted">
            SEO-статьи сайта. Нажмите на статью, чтобы отредактировать.
          </p>
        </div>
        <button
          onClick={() => router.push("/admin-new/blog/new")}
          className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-on-accent transition-opacity hover:opacity-90"
        >
          <FiPlus className="h-4 w-4" />
          Новая статья
        </button>
      </div>

      {error ? (
        <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
          Ошибка загрузки: {error}
        </div>
      ) : posts.length === 0 ? (
        <div className="rounded-2xl border border-border bg-surface p-8 text-center text-sm text-muted">
          Статей пока нет. Нажмите «Новая статья», чтобы создать первую.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-border bg-surface">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-2">
                <th className="px-4 py-3 font-medium">Заголовок</th>
                <th className="px-4 py-3 font-medium">URL</th>
                <th className="px-4 py-3 font-medium">Статус</th>
                <th className="px-4 py-3 font-medium">Дата</th>
              </tr>
            </thead>
            <tbody>
              {posts.map((p) => (
                <tr
                  key={p.id}
                  onClick={() => router.push(`/admin-new/blog/${p.id}`)}
                  className="cursor-pointer border-b border-border last:border-0 hover:bg-surface-2"
                >
                  <td className="px-4 py-3 font-medium">{p.title_ru}</td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-2">/{p.slug}</td>
                  <td className="whitespace-nowrap px-4 py-3">
                    {p.is_published ? (
                      <span className="rounded-full bg-emerald-400/10 px-2.5 py-1 text-xs font-medium text-emerald-400">
                        Опубликована
                      </span>
                    ) : (
                      <span className="rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium text-muted">
                        Черновик
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-muted">
                    {fmtDate(p.published_at || p.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
