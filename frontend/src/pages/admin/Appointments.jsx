import { useEffect, useState } from "react";
import { apiClient } from "../../api/client.js";
import { Alert, Badge, Card, EmptyState, Spinner, statusTone } from "../../components/ui.jsx";
import { apiError, formatDateTime, statusLabel } from "../../lib/format.js";

function AdminAppointments() {
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get("/api/appointments");
        setAppointments(data.sort((a, b) => new Date(b.start_datetime) - new Date(a.start_datetime)));
      } catch (err) {
        setError(apiError(err, "Could not load appointments."));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="space-y-5">
      <h2 className="text-2xl font-semibold">Appointments</h2>
      {error ? <Alert>{error}</Alert> : null}
      {loading ? (
        <Spinner label="Loading appointments" />
      ) : appointments.length === 0 ? (
        <EmptyState title="No appointments" />
      ) : (
        <div className="space-y-3">
          {appointments.map((item) => (
            <Card key={item.id} className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-medium">
                  {item.patient_name || `Patient #${item.patient_id}`} with {item.doctor_name || `Doctor #${item.doctor_id}`}
                </p>
                <p className="text-sm text-stone-600">{formatDateTime(item.start_datetime)}</p>
              </div>
              <Badge tone={statusTone(item.status)}>{statusLabel(item.status)}</Badge>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default AdminAppointments;
