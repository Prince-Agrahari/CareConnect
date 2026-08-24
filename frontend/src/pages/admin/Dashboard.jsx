import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Card, Spinner } from "../../components/ui.jsx";
import { apiError } from "../../lib/format.js";

function AdminDashboard() {
  const notice = useLocation().state?.notice;
  const [doctors, setDoctors] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [d, a, n] = await Promise.all([
          apiClient.get("/api/admin/doctors"),
          apiClient.get("/api/appointments"),
          apiClient.get("/api/admin/notifications"),
        ]);
        setDoctors(d.data);
        setAppointments(a.data);
        setNotifications(n.data);
      } catch (err) {
        setError(apiError(err, "Could not load dashboard data."));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const pending = notifications.filter((item) => ["pending", "retrying", "failed"].includes(item.status)).length;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Clinic administration</h2>
        <p className="mt-1 text-stone-600">Manage doctors, hours, leave, and notification delivery.</p>
      </div>
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {error ? <Alert>{error}</Alert> : null}
      {loading ? (
        <Spinner label="Loading dashboard" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-3">
          <Link to="/admin/doctors">
            <Card>
              <p className="text-sm text-stone-500">Doctors</p>
              <p className="mt-2 text-3xl font-semibold">{doctors.length}</p>
            </Card>
          </Link>
          <Link to="/admin/appointments">
            <Card>
              <p className="text-sm text-stone-500">Appointments</p>
              <p className="mt-2 text-3xl font-semibold">{appointments.length}</p>
            </Card>
          </Link>
          <Link to="/admin/notifications">
            <Card>
              <p className="text-sm text-stone-500">Needs attention</p>
              <p className="mt-2 text-3xl font-semibold">{pending}</p>
            </Card>
          </Link>
        </div>
      )}
    </div>
  );
}

export default AdminDashboard;
