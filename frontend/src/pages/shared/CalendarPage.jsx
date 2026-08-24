import { useEffect, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Button, Card, EmptyState, Spinner } from "../../components/ui.jsx";
import { apiError, formatDateTime } from "../../lib/format.js";

function CalendarPage() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(location.state?.notice || "");
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const { data } = await apiClient.get("/api/v1/calendar/status");
      setStatus(data);
    } catch (err) {
      setError(apiError(err, "Could not load calendar status."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const calendar = params.get("calendar");
    const reason = params.get("reason");
    if (calendar === "connected") {
      setNotice("Google Calendar connected.");
    } else if (calendar === "error") {
      setError(reason ? `Calendar connection failed (${reason}).` : "Calendar connection failed.");
    }
    if (calendar) {
      params.delete("calendar");
      params.delete("reason");
      setParams(params, { replace: true });
    }
    load();
  }, []);

  async function connect() {
    setBusy(true);
    setError("");
    try {
      const { data } = await apiClient.get("/api/v1/calendar/connect");
      if (data.authorization_url) {
        window.location.assign(data.authorization_url);
        return;
      }
      setError("Google Calendar is not configured.");
    } catch (err) {
      setError(apiError(err, "Could not start Google Calendar connection."));
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError("");
    try {
      const { data } = await apiClient.post("/api/v1/calendar/disconnect");
      setStatus(data);
      setNotice("Google Calendar disconnected.");
    } catch (err) {
      setError(apiError(err, "Could not disconnect Google Calendar."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold">Google Calendar</h2>
        <p className="mt-1 text-sm text-stone-600">
          Confirmed visits can be added to your calendar. Tokens stay on the server and are never shown here.
        </p>
      </div>
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {error ? <Alert>{error}</Alert> : null}
      {loading ? (
        <Spinner label="Loading calendar status" />
      ) : status?.connected ? (
        <Card>
          <p className="font-medium text-stone-900">Connected to Google Calendar</p>
          <p className="mt-1 text-sm text-stone-600">Calendar: {status.google_calendar_id || "primary"}</p>
          <p className="mt-1 text-xs text-stone-500">Last checked {formatDateTime(new Date().toISOString())}</p>
          <Button className="mt-4" variant="secondary" disabled={busy} onClick={disconnect}>
            {busy ? "Disconnecting…" : "Disconnect"}
          </Button>
        </Card>
      ) : (
        <EmptyState
          title="Calendar is not connected"
          body="Connect Google Calendar to create, update, and remove events when appointments are confirmed, rescheduled, or cancelled."
          action={
            <Button disabled={busy} onClick={connect}>
              {busy ? "Redirecting…" : "Connect Google Calendar"}
            </Button>
          }
        />
      )}
      <Link className="text-sm font-semibold text-teal-800" to="..">
        Back to dashboard
      </Link>
    </div>
  );
}

export default CalendarPage;
