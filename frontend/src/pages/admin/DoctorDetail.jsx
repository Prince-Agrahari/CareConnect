import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Badge, Button, Card, Modal, Spinner, statusTone } from "../../components/ui.jsx";
import { apiError, formatDate, formatTime } from "../../lib/format.js";

function AdminDoctorDetail() {
  const { doctorId } = useParams();
  const navigate = useNavigate();
  const notice = useLocation().state?.notice;
  const [doctor, setDoctor] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(null);

  async function load() {
    setLoading(true);
    try {
      const { data } = await apiClient.get(`/api/admin/doctors/${doctorId}`);
      setDoctor(data);
    } catch (err) {
      setError(apiError(err, "Could not load doctor."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [doctorId]);

  async function toggleActive() {
    setBusy(true);
    try {
      const path = doctor.is_active ? "deactivate" : "activate";
      const { data } = await apiClient.post(`/api/admin/doctors/${doctorId}/${path}`);
      setDoctor(data);
      setConfirm(null);
    } catch (err) {
      setError(apiError(err, "Could not update doctor status."));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner label="Loading doctor" />;
  if (!doctor) return <Alert>{error || "Doctor not found."}</Alert>;

  return (
    <div className="space-y-5">
      <Link className="text-sm font-semibold text-teal-800" to="/admin/doctors">
        ← Doctors
      </Link>
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {error ? <Alert>{error}</Alert> : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold">{doctor.full_name}</h2>
          <p className="text-stone-600">
            {doctor.specialization} · {doctor.email}
          </p>
        </div>
        <Badge tone={statusTone(doctor.is_active ? "active" : "cancelled")}>{doctor.is_active ? "Active" : "Inactive"}</Badge>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => navigate(`/admin/doctors/${doctorId}/edit`)}>
          Edit doctor
        </Button>
        <Button variant="secondary" onClick={() => navigate(`/admin/doctors/${doctorId}/hours`)}>
          Working hours
        </Button>
        <Button variant="secondary" onClick={() => navigate(`/admin/doctors/${doctorId}/leave`)}>
          Leave
        </Button>
        <Button variant={doctor.is_active ? "danger" : "primary"} onClick={() => setConfirm(true)}>
          {doctor.is_active ? "Deactivate" : "Activate"}
        </Button>
      </div>
      <Card>
        <h3 className="font-semibold">Slot duration</h3>
        <p className="mt-1 text-sm">{doctor.slot_duration_minutes} minutes</p>
      </Card>
      <Card>
        <h3 className="font-semibold">Working hours</h3>
        {doctor.working_hours?.length ? (
          <ul className="mt-2 space-y-1 text-sm">
            {doctor.working_hours.map((item) => (
              <li key={item.id}>
                Day {item.day_of_week}: {formatTime(item.start_time)} – {formatTime(item.end_time)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-stone-600">None set.</p>
        )}
      </Card>
      <Card>
        <h3 className="font-semibold">Leave</h3>
        {doctor.leaves?.length ? (
          <ul className="mt-2 space-y-1 text-sm">
            {doctor.leaves.map((item) => (
              <li key={item.id}>
                {formatDate(item.start_date)} – {formatDate(item.end_date)} · {item.status}
                {item.reason ? ` · ${item.reason}` : ""}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-stone-600">No leave recorded.</p>
        )}
      </Card>
      {confirm ? (
        <Modal
          title={doctor.is_active ? "Deactivate this doctor?" : "Activate this doctor?"}
          onClose={() => setConfirm(null)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setConfirm(null)}>
                Cancel
              </Button>
              <Button disabled={busy} onClick={toggleActive}>
                {busy ? "Saving…" : "Confirm"}
              </Button>
            </>
          }
        >
          {doctor.is_active
            ? "Inactive doctors cannot accept new bookings. Existing appointments stay in history."
            : "This doctor will be able to accept bookings again."}
        </Modal>
      ) : null}
    </div>
  );
}

export default AdminDoctorDetail;
