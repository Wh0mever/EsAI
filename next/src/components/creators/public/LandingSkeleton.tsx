/**
 * Заглушка страницы программы, пока грузятся условия и переводы. Повторяет
 * первый экран (заголовок, подзаголовок, кнопка, карточки), чтобы страница не
 * прыгала, когда придёт ответ.
 */
export default function LandingSkeleton() {
  const bar = "animate-pulse rounded-2xl bg-surface-2";

  return (
    <main aria-busy="true" className="relative min-h-[100dvh] overflow-hidden pb-20">
      <section className="px-4 pb-10 pt-28 sm:pb-14 sm:pt-36">
        <div className="mx-auto flex max-w-3xl flex-col items-center gap-4">
          <div className={`${bar} h-6 w-32`} />
          <div className={`${bar} h-10 w-full max-w-xl`} />
          <div className={`${bar} h-10 w-4/5 max-w-lg`} />
          <div className={`${bar} h-5 w-full max-w-md`} />
          <div className={`${bar} mt-3 h-12 w-56`} />
        </div>
      </section>
      <section className="mx-auto max-w-5xl px-4 py-6">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className={`${bar} col-span-2 h-[4.5rem]`} />
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className={`${bar} h-24 sm:h-[4.5rem]`} />
          ))}
        </div>
      </section>
    </main>
  );
}
