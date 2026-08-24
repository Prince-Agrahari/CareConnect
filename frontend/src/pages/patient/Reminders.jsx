import { useEffect, useState } from "react";
import { apiClient } from "../../api/client.js";
import { Alert, Badge, Card, EmptyState, Spinner, statusTone } from "../../components/ui.jsx";
import { apiError, formatDate, formatTime, statusLabel } from "../../lib/format.js";

function MedicationReminders() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get("/api/me/medication-reminders");
        setRows(data);
      } catch (err) {
        setError(apiError(err, "Could not load medication reminders."));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold">Medication reminders</h2>
        <p className="mt-1 text-sm text-stone-600">
          Reminders are created only when a prescription includes explicit times. They do not change your prescription.
        </p>
      </div>
      {error ? <Alert>{error}</Alert> : null}
      {loading ? (
        <Spinner label="Loading reminders" />
      ) : rows.length === 0 ? (
        <EmptyState title="No reminders" body="When a doctor records a schedule with clock times, reminders will appear here." />
      ) : (
        <div className="grid gap-3">
          {rows.map((row) => (
            <Card key={row.id} className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-medium">{row.medicine_name}</p>
                <p className="text-sm text-stone-600">
                  {row.dosage} · {row.frequency} · {row.duration}
                </p>
                <p className="mt-1 text-sm">
                  {formatTime(row.remind_at)} · {formatDate(row.start_date)} to {formatDate(row.end_date)}
                </p>
              </div>
              <Badge tone={statusTone(row.status)}>{statusLabel(row.status)}</Badge>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default MedicationReminders;
