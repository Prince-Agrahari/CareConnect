export function Spinner({ label = "Loading" }) {
  return (
    <div className="flex items-center gap-3 text-teal-800" role="status" aria-live="polite">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-teal-700 border-t-transparent" />
      <span className="text-sm font-medium">{label}…</span>
    </div>
  );
}

export function Alert({ tone = "error", children }) {
  const tones = {
    error: "border-rose-200 bg-rose-50 text-rose-900",
    success: "border-teal-200 bg-teal-50 text-teal-900",
    info: "border-stone-200 bg-white text-stone-700",
  };
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm ${tones[tone] || tones.info}`} role="alert">
      {children}
    </div>
  );
}

export function EmptyState({ title, body, action }) {
  return (
    <div className="rounded-2xl border border-dashed border-stone-300 bg-white/70 px-6 py-12 text-center">
      <h3 className="text-lg font-semibold text-stone-900">{title}</h3>
      {body ? <p className="mx-auto mt-2 max-w-md text-sm text-stone-600">{body}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }) {
  const tones = {
    neutral: "bg-stone-100 text-stone-700",
    success: "bg-teal-100 text-teal-900",
    warn: "bg-amber-100 text-amber-900",
    danger: "bg-rose-100 text-rose-900",
    info: "bg-sky-100 text-sky-900",
  };
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${tones[tone] || tones.neutral}`}>
      {children}
    </span>
  );
}

export function Field({ label, error, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-stone-700">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-sm text-rose-700">{error}</span> : null}
    </label>
  );
}

export const inputClass =
  "w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 text-stone-900 outline-none ring-teal-700/20 focus:border-teal-700 focus:ring-4";

export function Button({ children, variant = "primary", className = "", ...props }) {
  const variants = {
    primary: "bg-teal-800 text-white hover:bg-teal-900 disabled:bg-teal-800/50",
    secondary: "bg-white text-stone-800 ring-1 ring-stone-300 hover:bg-stone-50",
    danger: "bg-rose-700 text-white hover:bg-rose-800 disabled:bg-rose-700/50",
    ghost: "text-teal-800 hover:bg-teal-50",
  };
  return (
    <button
      className={`inline-flex items-center justify-center rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:cursor-not-allowed ${variants[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function Card({ children, className = "" }) {
  return <section className={`rounded-2xl border border-stone-200 bg-white p-5 shadow-sm ${className}`}>{children}</section>;
}

export function Modal({ title, children, onClose, footer }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 p-4 sm:items-center">
      <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <div className="flex items-start justify-between gap-4">
          <h2 id="dialog-title" className="text-lg font-semibold text-stone-900">
            {title}
          </h2>
          <button type="button" className="text-stone-500 hover:text-stone-800" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="mt-3 text-sm text-stone-600">{children}</div>
        {footer ? <div className="mt-5 flex justify-end gap-2">{footer}</div> : null}
      </div>
    </div>
  );
}

export function statusTone(status) {
  if (["confirmed", "sent", "synced", "active", "succeeded"].includes(status)) return "success";
  if (["cancelled", "cancelled_leave", "failed", "deleted"].includes(status)) return "danger";
  if (["pending", "retrying", "rescheduled"].includes(status)) return "warn";
  if (["completed"].includes(status)) return "info";
  return "neutral";
}
