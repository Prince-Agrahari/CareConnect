export const SLOT_CONFLICT_MESSAGE =
  "This slot was just booked by another patient. Please select another slot.";

export function apiError(error, fallback = "Something went wrong. Please try again.") {
  const status = error?.response?.status;
  const detail = error?.response?.data?.detail;
  const text = formatDetail(detail);
  if (status === 409) {
    if (!text || /slot|available|book|hold|overlap|no longer/i.test(text)) {
      return SLOT_CONFLICT_MESSAGE;
    }
    return text;
  }
  return text || fallback;
}

function formatDetail(detail) {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "string" ? item : item?.msg || ""))
      .filter(Boolean)
      .join(" ");
  }
  if (typeof detail === "object" && detail.msg) return detail.msg;
  return "";
}

export function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatDate(value) {
  if (!value) return "—";
  const date = value instanceof Date ? value : new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatTime(value) {
  if (!value) return "—";
  if (typeof value === "string" && /^\d{2}:\d{2}/.test(value)) {
    const [hours, minutes] = value.split(":");
    const date = new Date();
    date.setHours(Number(hours), Number(minutes), 0, 0);
    return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function toDateInput(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function isSameDay(value, other = new Date()) {
  const left = new Date(value);
  const right = other instanceof Date ? other : new Date(other);
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

export function isUpcoming(value) {
  return new Date(value).getTime() >= Date.now();
}

export const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function statusLabel(status) {
  return String(status || "").replaceAll("_", " ");
}

export function portalHome(role) {
  if (role === "doctor") return "/doctor";
  if (role === "admin") return "/admin";
  return "/patient";
}
