import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Button, Card, Field, Spinner, inputClass } from "../../components/ui.jsx";
import { apiError, formatDateTime, formatTime, toDateInput } from "../../lib/format.js";

function RescheduleAppointment() {
  const { appointmentId } = useParams();
  const navigate = useNavigate();
  const [appointment, setAppointment] = useState(null);
  const [date, setDate] = useState(toDateInput());
  const [slots, setSlots] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get(`/api/appointments/${appointmentId}`);
        setAppointment(data);
      } catch (err) {
        setError(apiError(err, "Could not load this appointment."));
      } finally {
        setLoading(false);
      }
    })();
  }, [appointmentId]);

  useEffect(() => {
    if (!appointment) return undefined;
    let cancelled = false;
    (async () => {
      setSlotsLoading(true);
      try {
        const { data } = await apiClient.get(`/api/doctors/${appointment.doctor_id}/availability`, {
          params: { date },
        });
        if (!cancelled) setSlots(data.slots || []);
      } catch (err) {
        if (!cancelled) setError(apiError(err, "Could not load availability."));
      } finally {
        if (!cancelled) setSlotsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [appointment, date]);

  async function choose(slot) {
    setBusy(true);
    setError("");
    try {
      const { data: hold } = await apiClient.post("/api/appointments/hold", {
        doctor_id: appointment.doctor_id,
        start_datetime: slot.start_datetime,
        end_datetime: slot.end_datetime,
      });
      const { data } = await apiClient.post(`/api/appointments/${appointmentId}/reschedule`, {
        hold_id: hold.id,
      });
      navigate(`/patient/appointments/${data.id}`, {
        replace: true,
        state: { notice: "Appointment rescheduled." },
      });
    } catch (err) {
      setError(apiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner label="Loading appointment" />;
  if (!appointment) return <Alert>{error || "Appointment not found."}</Alert>;

  return (
    <div className="space-y-5">
      <Link className="text-sm font-semibold text-teal-800" to={`/patient/appointments/${appointmentId}`}>
        ← Appointment details
      </Link>
      <h2 className="text-2xl font-semibold">Reschedule</h2>
      <Card>
        <p className="text-sm text-stone-600">Current time: {formatDateTime(appointment.start_datetime)}</p>
      </Card>
      {error ? <Alert>{error}</Alert> : null}
      <Field label="New date">
        <input className={inputClass} type="date" min={toDateInput()} value={date} onChange={(e) => setDate(e.target.value)} />
      </Field>
      {slotsLoading ? (
        <Spinner label="Loading slots" />
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
          {slots.map((slot) => (
            <Button key={slot.start_datetime} variant="secondary" disabled={busy} onClick={() => choose(slot)}>
              {formatTime(slot.start_datetime)}
            </Button>
          ))}
        </div>
      )}
      {!slotsLoading && slots.length === 0 ? <p className="text-sm text-stone-600">No open slots on this date.</p> : null}
    </div>
  );
}

export default RescheduleAppointment;
