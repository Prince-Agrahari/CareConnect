import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Button, Field, Spinner, inputClass } from "../../components/ui.jsx";
import { apiError } from "../../lib/format.js";

function DoctorForm() {
  const { doctorId } = useParams();
  const isNew = !doctorId;
  const navigate = useNavigate();
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [errors, setErrors] = useState({});
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    specialization: "",
    qualification: "",
    bio: "",
    slot_duration_minutes: 30,
    is_active: true,
  });

  useEffect(() => {
    if (isNew) return undefined;
    (async () => {
      try {
        const { data } = await apiClient.get(`/api/admin/doctors/${doctorId}`);
        setForm({
          full_name: data.full_name || "",
          email: data.email || "",
          password: "",
          specialization: data.specialization || "",
          qualification: data.qualification || "",
          bio: data.bio || "",
          slot_duration_minutes: data.slot_duration_minutes || 30,
          is_active: data.is_active,
        });
      } catch (err) {
        setError(apiError(err, "Could not load doctor."));
      } finally {
        setLoading(false);
      }
    })();
    return undefined;
  }, [doctorId, isNew]);

  function update(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function validate() {
    const next = {};
    if (!form.full_name.trim()) next.full_name = "Name is required.";
    if (isNew && !form.email.trim()) next.email = "Email is required.";
    if (isNew && form.password.length < 8) next.password = "Password must be at least 8 characters.";
    if (!form.specialization.trim()) next.specialization = "Specialization is required.";
    const duration = Number(form.slot_duration_minutes);
    if (!duration || duration < 5 || duration > 180) next.slot_duration_minutes = "Slot duration must be between 5 and 180 minutes.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    if (!validate()) return;
    setSaving(true);
    try {
      if (isNew) {
        const { data } = await apiClient.post("/api/admin/doctors", {
          full_name: form.full_name.trim(),
          email: form.email.trim(),
          password: form.password,
          specialization: form.specialization.trim(),
          qualification: form.qualification.trim() || null,
          bio: form.bio.trim() || null,
          slot_duration_minutes: Number(form.slot_duration_minutes),
          is_active: form.is_active,
        });
        navigate(`/admin/doctors/${data.id}`, { state: { notice: "Doctor created." } });
      } else {
        await apiClient.patch(`/api/admin/doctors/${doctorId}`, {
          full_name: form.full_name.trim(),
          specialization: form.specialization.trim(),
          qualification: form.qualification.trim() || null,
          bio: form.bio.trim() || null,
          slot_duration_minutes: Number(form.slot_duration_minutes),
          is_active: form.is_active,
        });
        navigate(`/admin/doctors/${doctorId}`, { state: { notice: "Doctor updated." } });
      }
    } catch (err) {
      setError(apiError(err, "Could not save doctor."));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Spinner label="Loading doctor" />;

  return (
    <form onSubmit={onSubmit} className="max-w-xl space-y-4">
      <Link className="text-sm font-semibold text-teal-800" to="/admin/doctors">
        ← Doctors
      </Link>
      <h2 className="text-2xl font-semibold">{isNew ? "Create doctor" : "Edit doctor"}</h2>
      {error ? <Alert>{error}</Alert> : null}
      <Field label="Full name" error={errors.full_name}>
        <input className={inputClass} value={form.full_name} onChange={(e) => update("full_name", e.target.value)} />
      </Field>
      {isNew ? (
        <>
          <Field label="Email" error={errors.email}>
            <input className={inputClass} type="email" value={form.email} onChange={(e) => update("email", e.target.value)} />
          </Field>
          <Field label="Temporary password" error={errors.password}>
            <input className={inputClass} type="password" value={form.password} onChange={(e) => update("password", e.target.value)} />
          </Field>
        </>
      ) : (
        <p className="text-sm text-stone-600">{form.email}</p>
      )}
      <Field label="Specialization" error={errors.specialization}>
        <input className={inputClass} value={form.specialization} onChange={(e) => update("specialization", e.target.value)} />
      </Field>
      <Field label="Qualification">
        <input className={inputClass} value={form.qualification} onChange={(e) => update("qualification", e.target.value)} />
      </Field>
      <Field label="Bio">
        <textarea className={`${inputClass} min-h-24`} value={form.bio} onChange={(e) => update("bio", e.target.value)} />
      </Field>
      <Field label="Slot duration (minutes)" error={errors.slot_duration_minutes}>
        <input
          className={inputClass}
          type="number"
          min="5"
          max="180"
          value={form.slot_duration_minutes}
          onChange={(e) => update("slot_duration_minutes", e.target.value)}
        />
      </Field>
      {!isNew ? (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.is_active} onChange={(e) => update("is_active", e.target.checked)} />
          Active (can accept bookings)
        </label>
      ) : null}
      <Button type="submit" disabled={saving}>
        {saving ? "Saving…" : isNew ? "Create doctor" : "Save changes"}
      </Button>
    </form>
  );
}

export default DoctorForm;
