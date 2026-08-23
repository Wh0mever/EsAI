/**
 * Страховка от «сайта без стилей».
 *
 * Имена файлов Next содержат хэш, и при выкладке старые исчезают. Если у
 * человека страница осталась от прошлой сборки — из кэша браузера, из
 * service worker или предзагруженная поиском Google, — её css отдаёт 404, и
 * сайт открывается голым HTML: засечки, синие ссылки, «Выбрать файлы». В логах
 * nginx такие 404 были со 159 разных адресов.
 *
 * Основное лечение — на сервере: статика прошлых сборок больше не удаляется
 * (nginx location /_next/static/ + scripts/sync-next-static.sh). Этот скрипт —
 * второй рубеж на случай, когда сборка старше срока хранения: страница сама
 * замечает, что осталась без стилей, чистит кэши и перезагружается один раз.
 *
 * Почему проверка через реальный элемент, а не по document.styleSheets: лист
 * может присутствовать в списке и при этом не примениться (например,
 * отдался HTML-ответ 404 вместо css). Пробуем то, что важно на деле — что
 * утилитарные классы Tailwind действительно работают.
 */
export const CSS_GUARD = `
(function () {
  var FLAG = "esai-css-reload";
  function healthy() {
    try {
      var probe = document.createElement("div");
      probe.className = "hidden";
      probe.setAttribute("aria-hidden", "true");
      document.body.appendChild(probe);
      var ok = getComputedStyle(probe).display === "none";
      probe.remove();
      return ok;
    } catch (e) {
      return true; // не смогли проверить — не трогаем страницу
    }
  }
  function heal() {
    if (healthy()) {
      try { sessionStorage.removeItem(FLAG); } catch (e) {}
      return;
    }
    // Перезагружаем ровно один раз за вкладку: если стилей нет и после
    // перезагрузки, значит дело не в кэше, и бесконечный цикл только добьёт.
    try { if (sessionStorage.getItem(FLAG)) return; sessionStorage.setItem(FLAG, "1"); } catch (e) {}
    var done = function () { location.reload(); };
    var jobs = [];
    try {
      if (window.caches && caches.keys) {
        jobs.push(caches.keys().then(function (ks) {
          return Promise.all(ks.map(function (k) { return caches.delete(k); }));
        }));
      }
    } catch (e) {}
    try {
      if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
        jobs.push(navigator.serviceWorker.getRegistrations().then(function (rs) {
          return Promise.all(rs.map(function (r) { return r.unregister(); }));
        }));
      }
    } catch (e) {}
    if (!jobs.length) return done();
    Promise.all(jobs).then(done, done);
    // Страховка от зависшего промиса: перезагрузка всё равно состоится.
    setTimeout(done, 1500);
  }
  // Ждём load: до него css мог просто не успеть приехать.
  if (document.readyState === "complete") heal();
  else window.addEventListener("load", function () { setTimeout(heal, 300); });
})();
`;
