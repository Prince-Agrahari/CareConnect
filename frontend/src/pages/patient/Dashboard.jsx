import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Badge, Card, EmptyState, Spinner, statusTone } from "../../components/ui.jsx";
import { apiError, formatDateTime, isUpcoming, statusLabel } from "../../lib/format.js";
import { useAuth } from "../../context/AuthContext.jsx";

function PatientDashboard() {
  const { user } = useAuth();
  const notice = useLocation().state?.notice;
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await apiClient.get("/api/appointments");
        if (!cancelled) setAppointments(data);
      } catch (err) {
        if (!cancelled) setError(apiError(err, "Could not load appointments."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const upcoming = useMemo(
    () =>
      appointments
        .filter((item) => ["pending", "confirmed"].includes(item.status) && isUpcoming(item.start_datetime))
        .sort((a, b) => new Date(a.start_datetime) - new Date(b.start_datetime)),
    [appointments]
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Hello, {user?.full_name?.split(" ")[0]}</h2>
        <p className="mt-1 text-stone-600">Book a visit, review prescriptions, and keep follow-up reminders in one place.</p>
      </div>
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {error ? <Alert>{error}</Alert> : null}
      <div className="grid gap-4 sm:grid-cols-3">
        <Link to="/patient/doctors" className="rounded-2xl bg-teal-800 p-5 text-white hover:bg-teal-900">
          <p className="text-sm opacity-80">Find care</p>
          <p className="mt-2 text-lg font-semibold">Search doctors</p>
        </Link>
        <Link to="/patient/appointments" className="rounded-2xl bg-white p-5 ring-1 ring-stone-200 hover:bg-stone-50">
          <p className="text-sm text-stone-500">Visits</p>
          <p className="mt-2 text-lg font-semibold">{appointments.length} appointments</p>
        </Link>
        <Link to="/patient/reminders" className="rounded-2xl bg-white p-5 ring-1 ring-stone-200 hover:bg-stone-50">
          <p className="text-sm text-stone-500">Follow-up</p>
          <p className="mt-2 text-lg font-semibold">Medication reminders</p>
        </Link>
      </div>
      <div>
        <h3 className="mb-3 text-lg font-semibold">Upcoming</h3>
        {loading ? (
          <Spinner label="Loading appointments" />
        ) : upcoming.length === 0 ? (
          <EmptyState
            title="No upcoming visits"
            body="Search for a doctor and hold a slot when you are ready to book."
            action={
              <Link className="font-semibold text-teal-800" to="/patient/doctors">
                Find a doctor
              </Link>
            }
          />
        ) : (
          <div className="grid gap-3">
            {upcoming.slice(0, 4).map((item) => (
              <Link key={item.id} to={`/patient/appointments/${item.id}`}>
                <Card className="flex flex-wrap items-center justify-between gap-3 hover:border-teal-700">
                  <div>
                    <p className="font-medium">{item.doctor_name || `Doctor #${item.doctor_id}`}</p>
                    <p className="text-sm text-stone-600">{formatDateTime(item.start_datetime)}</p>
                  </div>
                  <Badge tone={statusTone(item.status)}>{statusLabel(item.status)}</Badge>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default PatientDashboard;
