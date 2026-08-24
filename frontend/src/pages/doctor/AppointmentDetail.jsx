import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Badge, Button, Card, Field, Spinner, inputClass, statusTone } from "../../components/ui.jsx";
import { apiError, formatDateTime, statusLabel } from "../../lib/format.js";

const emptyMed = () => ({
  medicine_name: "",
  dosage: "",
  frequency: "",
  duration: "",
  instructions: "",
});

function DoctorAppointmentDetail() {
  const { appointmentId } = useParams();
  const notice = useLocation().state?.notice;
  const navigate = useNavigate();
  const [appointment, setAppointment] = useState(null);
  const [visit, setVisit] = useState(null);
  const [previsit, setPrevisit] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [clinicalNotes, setClinicalNotes] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [medications, setMedications] = useState([emptyMed()]);
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [retrying, setRetrying] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const { data: appt } = await apiClient.get(`/api/appointments/${appointmentId}`);
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
        if (data.clinical_notes) setClinicalNotes(data.clinical_notes);
        if (data.follow_up_instructions) setFollowUp(data.follow_up_instructions);
        if (data.medications?.length) {
          setMedications(
            data.medications.map((med) => ({
              medicine_name: med.medicine_name,
              dosage: med.dosage,
              frequency: med.frequency,
              duration: med.duration,
              instructions: med.instructions || "",
            }))
          );
        }
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

  async function retryPrevisit() {
    setRetrying(true);
    try {
      const { data } = await apiClient.post(`/api/appointments/${appointmentId}/previsit-summary/retry`);
      setPrevisit(data);
    } catch (err) {
      setError(apiError(err, "Could not retry the AI summary."));
    } finally {
      setRetrying(false);
    }
  }

  async function retryVisitSummary() {
    setRetrying(true);
    try {
      const { data } = await apiClient.post(`/api/appointments/${appointmentId}/visit/summary/retry`);
      setVisit(data);
    } catch (err) {
      setError(apiError(err, "Could not retry the visit summary."));
    } finally {
      setRetrying(false);
    }
  }

  async function saveVisit(event) {
    event.preventDefault();
    if (!clinicalNotes.trim()) {
      setFormError("Clinical notes are required.");
      return;
    }
    const meds = medications
      .map((med) => ({
        medicine_name: med.medicine_name.trim(),
        dosage: med.dosage.trim(),
        frequency: med.frequency.trim(),
        duration: med.duration.trim(),
        instructions: med.instructions.trim() || null,
      }))
      .filter((med) => med.medicine_name || med.dosage || med.frequency || med.duration);
    for (const med of meds) {
      if (!med.medicine_name || !med.dosage || !med.frequency || !med.duration) {
        setFormError("Each medication needs name, dosage, frequency, and duration.");
        return;
      }
    }
    setFormError("");
    setSaving(true);
    try {
      const { data } = await apiClient.post(`/api/appointments/${appointmentId}/visit`, {
        clinical_notes: clinicalNotes.trim(),
        follow_up_instructions: followUp.trim() || null,
        medications: meds,
      });
      setVisit(data);
      navigate(`.`, { replace: true, state: { notice: "Visit notes saved." } });
      load();
    } catch (err) {
      setError(apiError(err, "Could not save visit notes."));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Spinner label="Loading appointment" />;
  if (!appointment) return <Alert>{error || "Appointment not found."}</Alert>;

  const hasVisit = Boolean(visit?.clinical_notes);

  return (
    <div className="space-y-5">
      <Link className="text-sm font-semibold text-teal-800" to="/doctor/appointments">
        ← Appointments
      </Link>
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {error ? <Alert>{error}</Alert> : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold">{appointment.patient_name || "Appointment details"}</h2>
          <p className="text-stone-600">{formatDateTime(appointment.start_datetime)}</p>
        </div>
        <Badge tone={statusTone(appointment.status)}>{statusLabel(appointment.status)}</Badge>
      </div>
      {previsit ? (
        <Card className="space-y-3">
          <h3 className="font-semibold">Patient symptoms</h3>
          <p className="whitespace-pre-wrap text-sm text-stone-700">{previsit.symptoms}</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="text-xs font-semibold uppercase text-stone-500">Urgency</p>
              <p>{previsit.urgency_level || "Pending"}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase text-stone-500">AI pre-visit status</p>
              <p>{statusLabel(previsit.status)}</p>
            </div>
          </div>
          {previsit.chief_complaint ? (
            <div>
              <p className="text-xs font-semibold uppercase text-stone-500">Chief complaint</p>
              <p>{previsit.chief_complaint}</p>
            </div>
          ) : null}
          {previsit.suggested_questions?.length ? (
            <div>
              <p className="text-xs font-semibold uppercase text-stone-500">Suggested questions</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                {previsit.suggested_questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <p className="text-xs text-stone-500">{previsit.disclaimer}</p>
          {previsit.status === "failed" ? (
            <Button variant="secondary" disabled={retrying} onClick={retryPrevisit}>
              Retry AI summary
            </Button>
          ) : null}
        </Card>
      ) : null}
      {hasVisit ? (
        <Card>
          <h3 className="font-semibold">Clinical notes</h3>
          <p className="mt-2 whitespace-pre-wrap text-sm">{visit.clinical_notes}</p>
          {visit.patient_friendly_summary ? (
            <div className="mt-4">
              <h4 className="font-medium">AI post-visit summary</h4>
              <p className="mt-1 whitespace-pre-wrap text-sm">{visit.patient_friendly_summary}</p>
              <p className="mt-2 text-xs text-stone-500">{visit.disclaimer}</p>
            </div>
          ) : (
            <div className="mt-4">
              <p className="text-sm text-stone-600">Patient summary status: {statusLabel(visit.summary_status)}</p>
              {visit.summary_status === "failed" ? (
                <Button className="mt-2" variant="secondary" disabled={retrying} onClick={retryVisitSummary}>
                  Retry patient summary
                </Button>
              ) : null}
            </div>
          )}
        </Card>
      ) : (
        <form onSubmit={saveVisit} className="space-y-4 rounded-2xl border border-stone-200 bg-white p-5">
          <h3 className="font-semibold">Record visit</h3>
          {formError ? <Alert>{formError}</Alert> : null}
          <Field label="Clinical notes">
            <textarea className={`${inputClass} min-h-32`} value={clinicalNotes} onChange={(e) => setClinicalNotes(e.target.value)} />
          </Field>
          <Field label="Follow-up instructions">
            <textarea className={`${inputClass} min-h-20`} value={followUp} onChange={(e) => setFollowUp(e.target.value)} />
          </Field>
          <div>
            <p className="mb-2 text-sm font-medium">Prescription</p>
            {medications.map((med, index) => (
              <div key={index} className="mb-3 grid gap-2 rounded-xl bg-stone-50 p-3 sm:grid-cols-2">
                <input className={inputClass} placeholder="Medicine" value={med.medicine_name} onChange={(e) => {
                  const next = [...medications];
                  next[index] = { ...med, medicine_name: e.target.value };
                  setMedications(next);
                }} />
                <input className={inputClass} placeholder="Dosage" value={med.dosage} onChange={(e) => {
                  const next = [...medications];
                  next[index] = { ...med, dosage: e.target.value };
                  setMedications(next);
                }} />
                <input className={inputClass} placeholder="Frequency (include times for reminders)" value={med.frequency} onChange={(e) => {
                  const next = [...medications];
                  next[index] = { ...med, frequency: e.target.value };
                  setMedications(next);
                }} />
                <input className={inputClass} placeholder="Duration" value={med.duration} onChange={(e) => {
                  const next = [...medications];
                  next[index] = { ...med, duration: e.target.value };
                  setMedications(next);
                }} />
                <input className={`${inputClass} sm:col-span-2`} placeholder="Instructions" value={med.instructions} onChange={(e) => {
                  const next = [...medications];
                  next[index] = { ...med, instructions: e.target.value };
                  setMedications(next);
                }} />
              </div>
            ))}
            <Button type="button" variant="ghost" onClick={() => setMedications([...medications, emptyMed()])}>
              Add medication
            </Button>
          </div>
          <Button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save notes and prescription"}
          </Button>
        </form>
      )}
    </div>
  );
}

export default DoctorAppointmentDetail;
