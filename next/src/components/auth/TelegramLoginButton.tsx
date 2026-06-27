"use client";

import { useEffect, useRef, useState } from "react";
import { fetchData } from "@/tools/fetchData";

type Props = {
  /** size of the official widget button */
  size?: "small" | "medium" | "large";
  /** corner radius of the widget button */
  cornerRadius?: number;
  className?: string;
};

type TelegramConfig = { bot_username?: string };

/**
 * TelegramLoginButton — renders the official Telegram Login Widget.
 *
 * It first fetches the bot username from `GET /api/users/telegram-config/`,
 * then injects Telegram's widget script (telegram-widget.js) into a container.
 * On success Telegram redirects the browser to `data-auth-url`, which is the
 * backend callback that issues our session/tokens.
 *
 * The script must run on the client, so this component mounts the <script>
 * element imperatively after the bot username is known.
 */
export default function TelegramLoginButton({
  size = "large",
  cornerRadius,
  className,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [botUsername, setBotUsername] = useState<string>("");
  const [error, setError] = useState(false);

  // 1) Resolve bot username from the backend config endpoint.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchData<TelegramConfig>("users/telegram-config/", "GET", null, false);
        const name = (res?.data as TelegramConfig | null)?.bot_username || "";
        if (!cancelled) {
          if (name) setBotUsername(name);
          else setError(true);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // 2) Inject the official widget script once we know the bot username.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !botUsername) return;

    // Clear any previous injection (e.g. on hot reload / re-mount).
    el.innerHTML = "";

    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.setAttribute("data-telegram-login", botUsername);
    script.setAttribute("data-size", size);
    if (typeof cornerRadius === "number") {
      script.setAttribute("data-radius", String(cornerRadius));
    }
    script.setAttribute("data-auth-url", "/api/users/accounts/telegram/login/callback/");
    script.setAttribute("data-request-access", "write");

    el.appendChild(script);

    return () => {
      el.innerHTML = "";
    };
  }, [botUsername, size, cornerRadius]);

  if (error) return null;

  return <div ref={containerRef} className={className} aria-label="Telegram login" />;
}
