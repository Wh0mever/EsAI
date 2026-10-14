// EsAI admin: «глазок» показать/скрыть пароль на всех input[type=password].
(function () {
  function addToggle(input) {
    if (!input || input.dataset.eyeified === "1") return;
    input.dataset.eyeified = "1";

    var wrap = document.createElement("span");
    wrap.style.cssText = "position:relative;display:inline-block;";
    if (input.parentNode) {
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);
    } else {
      return;
    }
    // место под кнопку
    input.style.paddingRight = "2.4em";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "👁";
    btn.title = "Показать/скрыть пароль";
    btn.setAttribute("aria-label", "Показать или скрыть пароль");
    btn.style.cssText =
      "position:absolute;right:.45em;top:50%;transform:translateY(-50%);" +
      "background:none;border:none;cursor:pointer;font-size:1.1em;opacity:.6;padding:0;line-height:1;";
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.style.opacity = show ? "1" : ".6";
    });
    wrap.appendChild(btn);
  }

  function run() {
    document.querySelectorAll('input[type="password"]').forEach(addToggle);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
  // На случай динамически добавленных полей (inline-формы и т.п.)
  document.addEventListener("formset:added", run);
})();
