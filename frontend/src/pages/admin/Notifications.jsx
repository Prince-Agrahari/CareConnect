import { useEffect, useState } from "react";
import { apiClient } from "../../api/client.js";
import { Alert, Badge, Card, EmptyState, Field, Spinner, inputClass, statusTone } from "../../components/ui.jsx";
import { apiError, formatDateTime, statusLabel } from "../../lib/format.js";

function NotificationsPage() {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const { data } = await apiClient.get("/api/admin/notifications", {
          params: status ? { status } : undefined,
        });
        if (!cancelled) setRows(data);
      } catch (err) {
        if (!cancelled) setError(apiError(err, "Could not load notifications."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status]);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold">Notification monitoring</h2>
        <p className="mt-1 text-sm text-stone-600">Email delivery status. Failures never un-book a visit.</p>
      </div>
      <Field label="Status">
        <select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          <option value="pending">Pending</option>
          <option value="retrying">Retrying</option>
          <option value="sent">Sent</option>
          <option value="failed">Failed</option>
        </select>
      </Field>
      {error ? <Alert>{error}</Alert> : null}
      {loading ? (
        <Spinner label="Loading notifications" />
      ) : rows.length === 0 ? (
        <EmptyState title="No notifications" />
      ) : (
        <div className="space-y-3">
          {rows.map((row) => (
            <Card key={row.id} className="space-y-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">{row.subject}</p>
                <Badge tone={statusTone(row.status)}>{statusLabel(row.status)}</Badge>
              </div>
              <p className="text-sm text-stone-600">
                {row.notification_type} · {row.recipient} · retries {row.retry_count}
              </p>
              <p className="text-xs text-stone-500">{formatDateTime(row.created_at)}</p>
              {row.error_message ? <p className="text-sm text-rose-700">{row.error_message}</p> : null}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default NotificationsPage;
