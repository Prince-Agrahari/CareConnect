import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Badge, Card, EmptyState, Spinner, statusTone } from "../../components/ui.jsx";
import { apiError, formatDateTime, isSameDay, isUpcoming, statusLabel } from "../../lib/format.js";
import { useAuth } from "../../context/AuthContext.jsx";

function splitAppointments(appointments) {
  const today = [];
  const upcoming = [];
  for (const item of appointments) {
    if (!["pending", "confirmed"].includes(item.status)) continue;
    if (isSameDay(item.start_datetime)) today.push(item);
    else if (isUpcoming(item.start_datetime)) upcoming.push(item);
  }
  today.sort((a, b) => new Date(a.start_datetime) - new Date(b.start_datetime));
  upcoming.sort((a, b) => new Date(a.start_datetime) - new Date(b.start_datetime));
  return { today, upcoming };
}

function AppointmentList({ title, items }) {
  if (items.length === 0) {
    return <EmptyState title={`No ${title.toLowerCase()}`} />;
  }
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <Link key={item.id} to={`/doctor/appointments/${item.id}`}>
          <Card className="flex flex-wrap items-center justify-between gap-3 hover:border-teal-700">
            <div>
              <p className="font-medium">{item.patient_name || `Patient #${item.patient_id}`}</p>
              <p className="text-sm text-stone-600">{formatDateTime(item.start_datetime)}</p>
            </div>
            <Badge tone={statusTone(item.status)}>{statusLabel(item.status)}</Badge>
          </Card>
        </Link>
      ))}
    </div>
  );
}

function DoctorDashboard() {
  const { user } = useAuth();
  const notice = useLocation().state?.notice;
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get("/api/appointments");
        setAppointments(data);
      } catch (err) {
        setError(apiError(err, "Could not load appointments."));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const { today, upcoming } = useMemo(() => splitAppointments(appointments), [appointments]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Today’s clinic, {user?.full_name?.split(" ")[0]}</h2>
        <p className="mt-1 text-stone-600">Review symptoms and AI summaries before each visit. Notes save even if AI fails.</p>
      </div>
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {error ? <Alert>{error}</Alert> : null}
      {loading ? (
        <Spinner label="Loading schedule" />
      ) : (
        <>
          <section>
            <h3 className="mb-3 text-lg font-semibold">Today’s appointments</h3>
            <AppointmentList title="Today’s appointments" items={today} />
          </section>
          <section>
            <h3 className="mb-3 text-lg font-semibold">Upcoming appointments</h3>
            <AppointmentList title="Upcoming appointments" items={upcoming} />
          </section>
        </>
      )}
    </div>
  );
}

export default DoctorDashboard;
export { splitAppointments, AppointmentList };
