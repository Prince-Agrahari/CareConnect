import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Button, Card, EmptyState, Field, Spinner, inputClass } from "../../components/ui.jsx";
import { DAY_NAMES, apiError, formatTime, toDateInput } from "../../lib/format.js";

function DoctorProfile() {
  const { doctorId } = useParams();
  const navigate = useNavigate();
  const [doctor, setDoctor] = useState(null);
  const [date, setDate] = useState(toDateInput());
  const [availability, setAvailability] = useState(null);
  const [loading, setLoading] = useState(true);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [error, setError] = useState("");
  const [slotError, setSlotError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const { data } = await apiClient.get(`/api/doctors/${doctorId}`);
        if (!cancelled) setDoctor(data);
      } catch (err) {
        if (!cancelled) setError(apiError(err, "Doctor not found."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [doctorId]);

  useEffect(() => {
    if (!doctor) return undefined;
    let cancelled = false;
    (async () => {
      setSlotsLoading(true);
      setSlotError("");
      try {
        const { data } = await apiClient.get(`/api/doctors/${doctorId}/availability`, { params: { date } });
        if (!cancelled) setAvailability(data);
      } catch (err) {
        if (!cancelled) setSlotError(apiError(err, "Could not load availability."));
      } finally {
        if (!cancelled) setSlotsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [doctor, doctorId, date]);

  const hours = useMemo(
    () => [...(doctor?.working_hours || [])].sort((a, b) => a.day_of_week - b.day_of_week || a.start_time.localeCompare(b.start_time)),
    [doctor]
  );

  if (loading) return <Spinner label="Loading doctor" />;
  if (error) return <Alert>{error}</Alert>;
  if (!doctor) return <EmptyState title="Doctor not found" />;

  return (
    <div className="space-y-6">
      <div>
        <Link className="text-sm font-semibold text-teal-800" to="/patient/doctors">
          ← All doctors
        </Link>
        <h2 className="mt-2 text-2xl font-semibold">{doctor.full_name}</h2>
        <p className="text-teal-800">{doctor.specialization}</p>
        {doctor.qualification ? <p className="mt-2 text-stone-600">{doctor.qualification}</p> : null}
        {doctor.bio ? <p className="mt-2 max-w-2xl text-stone-700">{doctor.bio}</p> : null}
        <p className="mt-2 text-sm text-stone-500">Slot duration {doctor.slot_duration_minutes} minutes</p>
      </div>
      <Card>
        <h3 className="font-semibold">Working hours</h3>
        {hours.length === 0 ? (
          <p className="mt-2 text-sm text-stone-600">No working hours published.</p>
        ) : (
          <ul className="mt-3 space-y-1 text-sm text-stone-700">
            {hours.map((item) => (
              <li key={item.id || `${item.day_of_week}-${item.start_time}`}>
                {DAY_NAMES[item.day_of_week]} {formatTime(item.start_time)} – {formatTime(item.end_time)}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card>
        <h3 className="font-semibold">Availability</h3>
        <div className="mt-3 max-w-xs">
          <Field label="Date">
            <input className={inputClass} type="date" value={date} min={toDateInput()} onChange={(e) => setDate(e.target.value)} />
          </Field>
        </div>
        {slotError ? (
          <div className="mt-3">
            <Alert>{slotError}</Alert>
          </div>
        ) : null}
        {!doctor.is_active ? (
          <p className="mt-3 text-sm text-rose-700">This doctor is not accepting bookings.</p>
        ) : slotsLoading ? (
          <div className="mt-4">
            <Spinner label="Loading slots" />
          </div>
        ) : availability?.slots?.length ? (
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
            {availability.slots.map((slot) => (
              <Button
                key={slot.start_datetime}
                variant="secondary"
                onClick={() =>
                  navigate(
                    `/patient/doctors/${doctorId}/book?start=${encodeURIComponent(slot.start_datetime)}&end=${encodeURIComponent(slot.end_datetime)}`
                  )
                }
              >
                {formatTime(slot.start_datetime)}
              </Button>
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm text-stone-600">No open slots on this date.</p>
        )}
      </Card>
    </div>
  );
}

export default DoctorProfile;
