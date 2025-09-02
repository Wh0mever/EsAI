// Alert.tsx
"use client";

import React, { useEffect, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import "./Alert.scss";
import { IoClose } from "react-icons/io5";
import { CgDanger } from "react-icons/cg";
import { IoIosCheckmarkCircleOutline } from "react-icons/io";

type AlertType = "success" | "error" | "info" | "warning";
type AlertPosition = "top" | "bottom" | "left" | "right";

interface AlertProps {
  title?: string;
  message?: string;
  type?: AlertType;
  onClose?: () => void;
  className?: string;
  show?: boolean;
  closeButton?: boolean;
  position?: AlertPosition;
  autoClose?: boolean;
  autoCloseDuration?: number;
  offset?: number; // px
}

export function Alert({
  title = "Alert",
  message = "This is an alert message.",
  type = "info",
  onClose,
  className = "",
  show = true,
  closeButton = true,
  position = "top",
  autoClose = true,
  autoCloseDuration = 3000,
  offset = 16,
}: AlertProps) {
  const timerRef = useRef<number | null>(null);

  // create #alert-root once
  const root = useMemo(() => {
    if (typeof document === "undefined") return null;
    let el = document.getElementById("alert-root");
    if (!el) {
      el = document.createElement("div");
      el.id = "alert-root";
      document.body.appendChild(el);
    }
    return el;
  }, []);

  // autoclose
  useEffect(() => {
    if (!show || !autoClose || !onClose) return;
    timerRef.current = window.setTimeout(onClose, autoCloseDuration);
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [show, autoClose, autoCloseDuration, onClose]);

  // Esc to close
  useEffect(() => {
    if (!show || !onClose) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [show, onClose]);

  if (!show || !root) return null;

  const posClass = `alert-pos-${position}`;
  const typeClass = `alert-${type}`;

  return createPortal(
    <div
      className={["alert", typeClass, posClass, className].join(" ")}
      style={
        position === "top"
          ? { top: offset }
          : position === "bottom"
          ? { bottom: offset }
          : position === "left"
          ? { left: offset }
          : { right: offset }
      }
      role="alert"
      aria-live="assertive"
      aria-atomic="true"
    >
      <div className="alert-content">
        <div className="alert-head">
          <h5 className="alert-title">
            {type === "error" && <CgDanger className="alert-icon" />}
            {type === "success" && <IoIosCheckmarkCircleOutline className="alert-icon" />}
            {type === "info" && <IoIosCheckmarkCircleOutline className="alert-icon" />}
            {title}
          </h5>
          {closeButton && (
            <button className="alert-close" onClick={onClose} aria-label="Close alert">
              <IoClose />
            </button>
          )}
        </div>
        {message && <p className="alert-message">{message}</p>}
      </div>
    </div>,
    root
  );
}
