import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Button, Spinner, inputClass } from "../../components/ui.jsx";
import { DAY_NAMES, apiError } from "../../lib/format.js";

const emptyRow = () => ({ day_of_week: 0, start_time: "09:00", end_time: "17:00" });

function WorkingHoursPage() {
  const { doctorId } = useParams();
  const navigate = useNavigate();
  const [rows, setRows] = useState([emptyRow()]);
  const [duration, setDuration] = useState(30);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get(`/api/admin/doctors/${doctorId}`);
        setDuration(data.slot_duration_minutes);
        if (data.working_hours?.length) {
          setRows(
            data.working_hours.map((item) => ({
              day_of_week: item.day_of_week,
              start_time: String(item.start_time).slice(0, 5),
              end_time: String(item.end_time).slice(0, 5),
            }))
          );
        }
      } catch (err) {
        setError(apiError(err, "Could not load working hours."));
      } finally {
        setLoading(false);
      }
    })();
  }, [doctorId]);

  async function save(event) {
    event.preventDefault();
    setError("");
    for (const row of rows) {
      if (row.start_time >= row.end_time) {
        setError("Each shift needs a start time before the end time.");
        return;
      }
    }
    setSaving(true);
    try {
      await apiClient.patch(`/api/admin/doctors/${doctorId}`, {
        slot_duration_minutes: Number(duration),
      });
      await apiClient.put(`/api/admin/doctors/${doctorId}/working-hours`, {
        hours: rows.map((row) => ({
          day_of_week: Number(row.day_of_week),
          start_time: `${row.start_time}:00`,
          end_time: `${row.end_time}:00`,
        })),
      });
      navigate(`/admin/doctors/${doctorId}`, { state: { notice: "Working hours and slot duration saved." } });
    } catch (err) {
      setError(apiError(err, "Could not save working hours."));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Spinner label="Loading hours" />;

  return (
    <form onSubmit={save} className="space-y-5">
      <Link className="text-sm font-semibold text-teal-800" to={`/admin/doctors/${doctorId}`}>
        ← Doctor
      </Link>
      <h2 className="text-2xl font-semibold">Working hours & slot duration</h2>
      {error ? <Alert>{error}</Alert> : null}
      <label className="block max-w-xs">
        <span className="mb-1 block text-sm font-medium">Slot duration (minutes)</span>
        <input className={inputClass} type="number" min="5" max="180" value={duration} onChange={(e) => setDuration(e.target.value)} />
      </label>
      <div className="space-y-3">
        {rows.map((row, index) => (
          <div key={index} className="grid gap-2 rounded-xl bg-white p-3 ring-1 ring-stone-200 sm:grid-cols-4">
            <select
              className={inputClass}
              value={row.day_of_week}
              onChange={(e) => {
                const next = [...rows];
                next[index] = { ...row, day_of_week: Number(e.target.value) };
                setRows(next);
              }}
            >
              {DAY_NAMES.map((name, day) => (
                <option key={name} value={day}>
                  {name}
                </option>
              ))}
            </select>
            <input
              className={inputClass}
              type="time"
              value={row.start_time}
              onChange={(e) => {
                const next = [...rows];
                next[index] = { ...row, start_time: e.target.value };
                setRows(next);
              }}
            />
            <input
              className={inputClass}
              type="time"
              value={row.end_time}
              onChange={(e) => {
                const next = [...rows];
                next[index] = { ...row, end_time: e.target.value };
                setRows(next);
              }}
            />
            <Button
              type="button"
              variant="ghost"
              onClick={() => setRows(rows.filter((_, i) => i !== index))}
            >
              Remove
            </Button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <Button type="button" variant="secondary" onClick={() => setRows([...rows, emptyRow()])}>
          Add shift
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}

export default WorkingHoursPage;
