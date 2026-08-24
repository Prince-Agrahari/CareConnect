import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Badge, Button, Card, EmptyState, Spinner, statusTone } from "../../components/ui.jsx";
import { apiError } from "../../lib/format.js";

function AdminDoctors() {
  const [doctors, setDoctors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get("/api/admin/doctors");
        setDoctors(data);
      } catch (err) {
        setError(apiError(err, "Could not load doctors."));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-semibold">Doctors</h2>
        <Link to="/admin/doctors/new">
          <Button>Create doctor</Button>
        </Link>
      </div>
      {error ? <Alert>{error}</Alert> : null}
      {loading ? (
        <Spinner label="Loading doctors" />
      ) : doctors.length === 0 ? (
        <EmptyState title="No doctors" body="Create a doctor account to start taking bookings." />
      ) : (
        <div className="grid gap-3">
          {doctors.map((doctor) => (
            <Link key={doctor.id} to={`/admin/doctors/${doctor.id}`}>
              <Card className="flex flex-wrap items-center justify-between gap-3 hover:border-teal-700">
                <div>
                  <p className="font-medium">{doctor.full_name}</p>
                  <p className="text-sm text-stone-600">
                    {doctor.specialization} · {doctor.email}
                  </p>
                </div>
                <Badge tone={statusTone(doctor.is_active ? "active" : "cancelled")}>
                  {doctor.is_active ? "Active" : "Inactive"}
                </Badge>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default AdminDoctors;
