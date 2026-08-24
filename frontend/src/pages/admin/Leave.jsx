import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Button, Field, Modal, inputClass } from "../../components/ui.jsx";
import { apiError, toDateInput } from "../../lib/format.js";

function LeavePage() {
  const { doctorId } = useParams();
  const navigate = useNavigate();
  const [start, setStart] = useState(toDateInput());
  const [end, setEnd] = useState(toDateInput());
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [saving, setSaving] = useState(false);

  function validate() {
    if (!start || !end) return "Start and end dates are required.";
    if (end < start) return "End date must be on or after the start date.";
    return "";
  }

  async function submit() {
    const message = validate();
    if (message) {
      setError(message);
      setConfirm(false);
      return;
    }
    setSaving(true);
    setError("");
    try {
      const { data } = await apiClient.post(`/api/admin/doctors/${doctorId}/leave`, {
        start_date: start,
        end_date: end,
        reason: reason.trim() || null,
      });
      const cancelled = data.cancelled_appointment_ids?.length || 0;
      navigate(`/admin/doctors/${doctorId}`, {
        state: {
          notice:
            cancelled > 0
              ? `Leave recorded. ${cancelled} appointment(s) were cancelled.`
              : "Leave recorded. No appointments were affected.",
        },
      });
    } catch (err) {
      setError(apiError(err, "Could not record leave."));
      setConfirm(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-lg space-y-5">
      <Link className="text-sm font-semibold text-teal-800" to={`/admin/doctors/${doctorId}`}>
        ← Doctor
      </Link>
      <h2 className="text-2xl font-semibold">Leave management</h2>
      <p className="text-sm text-stone-600">
        Recording leave cancels overlapping pending and confirmed visits. History is kept.
      </p>
      {error ? <Alert>{error}</Alert> : null}
      <Field label="Start date">
        <input className={inputClass} type="date" value={start} onChange={(e) => setStart(e.target.value)} />
      </Field>
      <Field label="End date">
        <input className={inputClass} type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
      </Field>
      <Field label="Reason (optional)">
        <textarea className={`${inputClass} min-h-20`} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <Button onClick={() => setConfirm(true)}>Record leave</Button>
      {confirm ? (
        <Modal
          title="Record leave and cancel overlapping visits?"
          onClose={() => setConfirm(false)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setConfirm(false)}>
                Back
              </Button>
              <Button variant="danger" disabled={saving} onClick={submit}>
                {saving ? "Saving…" : "Confirm leave"}
              </Button>
            </>
          }
        >
          Patients with visits in this window will be notified. This cannot be undone from the form.
        </Modal>
      ) : null}
    </div>
  );
}

export default LeavePage;
