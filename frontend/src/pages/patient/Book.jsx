import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Button, Card, Field, Spinner, inputClass } from "../../components/ui.jsx";
import { apiError, formatDateTime } from "../../lib/format.js";

function BookAppointment() {
  const { doctorId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const start = params.get("start");
  const end = params.get("end");
  const [doctor, setDoctor] = useState(null);
  const [reason, setReason] = useState("");
  const [symptoms, setSymptoms] = useState("");
  const [hold, setHold] = useState(null);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [holding, setHolding] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    apiClient.get(`/api/doctors/${doctorId}`).then(({ data }) => setDoctor(data)).catch(() => {});
  }, [doctorId]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const remaining = useMemo(() => {
    if (!hold?.expires_at) return null;
    return Math.max(0, Math.floor((new Date(hold.expires_at).getTime() - now) / 1000));
  }, [hold, now]);

  async function holdSlot() {
    setError("");
    setHolding(true);
    try {
      const { data } = await apiClient.post("/api/appointments/hold", {
        doctor_id: Number(doctorId),
        start_datetime: start,
        end_datetime: end,
      });
      setHold(data);
    } catch (err) {
      setError(apiError(err));
    } finally {
      setHolding(false);
    }
  }

  async function confirm() {
    const next = {};
    if (!symptoms.trim()) next.symptoms = "Symptoms are required before confirmation.";
    setErrors(next);
    if (Object.keys(next).length) return;
    setError("");
    setConfirming(true);
    try {
      const { data } = await apiClient.post("/api/appointments/confirm", {
        hold_id: hold.id,
        symptoms: symptoms.trim(),
        reason: reason.trim() || null,
      });
      navigate(`/patient/appointments/${data.id}`, {
        replace: true,
        state: { notice: "Your appointment is confirmed." },
      });
    } catch (err) {
      setError(apiError(err));
    } finally {
      setConfirming(false);
    }
  }

  if (!start || !end) {
    return <Alert>Choose a slot from the doctor’s availability first.</Alert>;
  }

  return (
    <div className="space-y-5">
      <Link className="text-sm font-semibold text-teal-800" to={`/patient/doctors/${doctorId}`}>
        ← Back to availability
      </Link>
      <h2 className="text-2xl font-semibold">Hold and confirm</h2>
      <Card className="space-y-2">
        <p className="font-medium">{doctor?.full_name || "Doctor"}</p>
        <p className="text-sm text-stone-600">{formatDateTime(start)} – {formatDateTime(end)}</p>
        {hold ? (
          <p className="text-sm text-teal-800">
            Slot held. {remaining === 0 ? "This hold has expired." : `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")} remaining.`}
          </p>
        ) : (
          <Button disabled={holding} onClick={holdSlot}>
            {holding ? "Holding slot…" : "Hold this slot"}
          </Button>
        )}
      </Card>
      {error ? <Alert>{error}</Alert> : null}
      <Card className="space-y-4">
        <h3 className="font-semibold">Symptom form</h3>
        <Field label="Reason for visit (optional)">
          <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <Field label="Symptoms" error={errors.symptoms}>
          <textarea
            className={`${inputClass} min-h-32`}
            value={symptoms}
            onChange={(e) => setSymptoms(e.target.value)}
            placeholder="Describe what you are experiencing."
          />
        </Field>
        <Button disabled={!hold || remaining === 0 || confirming} onClick={confirm}>
          {confirming ? "Confirming…" : "Confirm booking"}
        </Button>
      </Card>
    </div>
  );
}

export default BookAppointment;
