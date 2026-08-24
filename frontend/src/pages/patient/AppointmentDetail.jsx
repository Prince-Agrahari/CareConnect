import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Badge, Button, Card, Modal, Spinner, statusTone } from "../../components/ui.jsx";
import { apiError, formatDateTime, statusLabel } from "../../lib/format.js";

function PatientAppointmentDetail() {
  const { appointmentId } = useParams();
  const navigate = useNavigate();
  const notice = useLocation().state?.notice;
  const [appointment, setAppointment] = useState(null);
  const [visit, setVisit] = useState(null);
  const [previsit, setPrevisit] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [{ data: appt }] = await Promise.all([apiClient.get(`/api/appointments/${appointmentId}`)]);
      setAppointment(appt);
      try {
        const { data } = await apiClient.get(`/api/appointments/${appointmentId}/previsit-summary`);
        setPrevisit(data);
      } catch {
        setPrevisit(null);
      }
      try {
        const { data } = await apiClient.get(`/api/appointments/${appointmentId}/visit`);
        setVisit(data);
      } catch {
        setVisit(null);
      }
    } catch (err) {
      setError(apiError(err, "Could not load this appointment."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [appointmentId]);

  async function cancel() {
    setBusy(true);
    try {
      const { data } = await apiClient.post(`/api/appointments/${appointmentId}/cancel`, {
        reason: reason.trim() || null,
      });
      setAppointment(data);
      setCancelOpen(false);
      navigate(`.`, { replace: true, state: { notice: "Appointment cancelled." } });
    } catch (err) {
      setError(apiError(err, "Could not cancel this appointment."));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner label="Loading appointment" />;
  if (error && !appointment) return <Alert>{error}</Alert>;

  const canChange = ["pending", "confirmed"].includes(appointment?.status);

  return (
    <div className="space-y-5">
      <Link className="text-sm font-semibold text-teal-800" to="/patient/appointments">
        ← My appointments
      </Link>
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {error ? <Alert>{error}</Alert> : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold">{appointment.doctor_name || "Appointment details"}</h2>
          <p className="text-stone-600">{formatDateTime(appointment.start_datetime)}</p>
        </div>
        <Badge tone={statusTone(appointment.status)}>{statusLabel(appointment.status)}</Badge>
      </div>
      <Card className="space-y-2 text-sm">
        <p>Doctor: {appointment.doctor_name || appointment.doctor_id}</p>
        {appointment.doctor_specialization ? <p>{appointment.doctor_specialization}</p> : null}
        {appointment.reason ? <p>Reason: {appointment.reason}</p> : null}
        {appointment.cancellation_reason ? <p>Cancellation: {appointment.cancellation_reason}</p> : null}
      </Card>
      {canChange ? (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setCancelOpen(true)}>
            Cancel appointment
          </Button>
          <Link to={`/patient/appointments/${appointmentId}/reschedule`}>
            <Button>Reschedule</Button>
          </Link>
        </div>
      ) : null}
      {previsit ? (
        <Card>
          <h3 className="font-semibold">Symptoms</h3>
          <p className="mt-2 whitespace-pre-wrap text-sm text-stone-700">{previsit.symptoms}</p>
        </Card>
      ) : null}
      {visit?.patient_friendly_summary ? (
        <Card>
          <h3 className="font-semibold">AI visit summary</h3>
          <p className="mt-2 whitespace-pre-wrap text-stone-800">{visit.patient_friendly_summary}</p>
          <p className="mt-3 text-xs text-stone-500">{visit.disclaimer}</p>
        </Card>
      ) : null}
      {visit?.medications?.length ? (
        <Card>
          <h3 className="font-semibold">Prescription</h3>
          <ul className="mt-3 space-y-2 text-sm">
            {visit.medications.map((med) => (
              <li key={med.id} className="rounded-xl bg-stone-50 p-3">
                <p className="font-medium">{med.medicine_name}</p>
                <p className="text-stone-600">
                  {med.dosage} · {med.frequency} · {med.duration}
                </p>
                {med.instructions ? <p className="mt-1">{med.instructions}</p> : null}
              </li>
            ))}
          </ul>
          {visit.follow_up_instructions ? (
            <p className="mt-3 text-sm text-stone-700">Follow-up: {visit.follow_up_instructions}</p>
          ) : null}
        </Card>
      ) : null}
      {cancelOpen ? (
        <Modal
          title="Cancel this appointment?"
          onClose={() => setCancelOpen(false)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setCancelOpen(false)}>
                Keep visit
              </Button>
              <Button variant="danger" disabled={busy} onClick={cancel}>
                {busy ? "Cancelling…" : "Confirm cancellation"}
              </Button>
            </>
          }
        >
          <p>The visit stays in your history and the slot becomes available again.</p>
          <textarea
            className="mt-3 w-full rounded-xl border border-stone-300 p-2"
            placeholder="Reason (optional)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Modal>
      ) : null}
    </div>
  );
}

export default PatientAppointmentDetail;
