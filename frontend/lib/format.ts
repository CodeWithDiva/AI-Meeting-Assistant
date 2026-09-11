/**
 * Small, dependency-free formatting helpers shared by every page.
 */

import type { ActionItem } from "./api";

/** The API stores naive UTC timestamps; read them as UTC, not local time. */
export function serverDate(value?: string | null): Date | null {
  if (!value) return null;
  const hasZone = /([zZ]|[+-]\d\d:?\d\d)$/.test(value);
  const date = new Date(hasZone ? value : `${value.replace(" ", "T")}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value?: string | null, withYear = false): string {
  const date = serverDate(value);
  if (!date) return "—";
  return date.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(withYear || date.getFullYear() !== new Date().getFullYear() ? { year: "numeric" } : {}),
  });
}

export function formatDateTime(value?: string | null): string {
  const date = serverDate(value);
  if (!date) return "—";
  return date.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function relativeTime(value?: string | null): string {
  const date = serverDate(value);
  if (!date) return "";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return formatDate(value);
}

export type DueTone = "overdue" | "soon" | "normal" | "none" | "done";

/** How a task's deadline should read and look right now. */
export function dueInfo(task: Pick<ActionItem, "due_at" | "deadline" | "status">): {
  label: string;
  tone: DueTone;
} {
  const due = serverDate(task.due_at);
  if (!due) {
    return task.deadline ? { label: task.deadline, tone: "normal" } : { label: "No deadline", tone: "none" };
  }
  const endOfDay = due.getHours() === 23 && due.getMinutes() === 59;
  const now = new Date();
  const dayDiff = Math.round(
    (new Date(due.getFullYear(), due.getMonth(), due.getDate()).getTime() -
      new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) /
      86_400_000
  );
  const time = endOfDay ? "" : `, ${due.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
  let label: string;
  if (dayDiff === 0) label = `Today${time}`;
  else if (dayDiff === 1) label = `Tomorrow${time}`;
  else if (dayDiff === -1) label = `Yesterday${time}`;
  else if (dayDiff > 1 && dayDiff < 7) label = `${due.toLocaleDateString(undefined, { weekday: "short" })}${time}`;
  else label = `${due.toLocaleDateString(undefined, { day: "numeric", month: "short" })}${time}`;

  if (task.status === "done") return { label, tone: "done" };
  const msLeft = due.getTime() - now.getTime();
  if (msLeft < 0) return { label, tone: "overdue" };
  if (msLeft < 48 * 3_600_000) return { label, tone: "soon" };
  return { label, tone: "normal" };
}

export function initials(name?: string | null): string {
  const clean = (name || "").replace(/@.*/, "").trim();
  if (!clean) return "?";
  const parts = clean.split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

export function displayName(user?: { full_name?: string | null; email?: string | null } | null): string {
  if (!user) return "";
  return user.full_name || (user.email ? user.email.split("@")[0] : "");
}

export function platformLabel(platform?: string | null): string {
  const p = (platform || "").toLowerCase();
  if (p.includes("zoom")) return "Zoom";
  if (p.includes("meet")) return "Google Meet";
  if (p.includes("team")) return "Teams";
  if (p === "attach") return "Your device";
  if (p === "in_person") return "In person";
  return "Audio upload";
}

/** Recognise the platform from whatever the user is pasting, as they type. */
export function detectPlatform(link: string): "zoom" | "google_meet" | null {
  const value = link.trim().toLowerCase();
  if (!value) return null;
  if (value.includes("zoom.")) return "zoom";
  if (value.includes("meet.google.") || /^[a-z]{3,4}-[a-z]{3,4}-[a-z]{3,4}$/.test(value)) return "google_meet";
  if (/^\d[\d\s-]{8,}$/.test(value)) return "zoom";
  return null;
}

/** Value for an <input type="datetime-local"> from an API timestamp. */
export function toLocalInput(value?: string | null): string {
  const date = serverDate(value);
  if (!date) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export function clock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

export function statusLabel(status: string): string {
  if (status === "in_progress") return "In progress";
  if (status === "done") return "Done";
  return "To do";
}
