"use client";

import { useEffect } from "react";
import Cookies from "js-cookie";
import { useRouter, useSearchParams } from "next/navigation";

export default function AuthCallback() {
  const router = useRouter();
  const params = useSearchParams();

  useEffect(() => {
    const access = params.get("access");
    const refresh = params.get("refresh");
    const user = params.get("user");

    if (access && refresh) {
      // Clear old values
      Cookies.remove("access");
      Cookies.remove("refresh");
      Cookies.remove("user");
      Cookies.remove("sessionid");

      Cookies.set("access", access, { expires: 7 });
      Cookies.set("refresh", refresh, { expires: 15 });
      if (user) {
        Cookies.set("user", user);
      }
      router.replace("/profile");
    } else {
      router.replace("/auth/signin");
    }
  }, [params, router]);

  return (
    <div className="w-full h-full flex items-center justify-center">
      <span>Processing authentication…</span>
    </div>
  );
}

