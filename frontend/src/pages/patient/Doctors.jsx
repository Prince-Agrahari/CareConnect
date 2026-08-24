import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../../api/client.js";
import { Alert, Card, EmptyState, Field, Spinner, inputClass } from "../../components/ui.jsx";
import { apiError } from "../../lib/format.js";

function PatientDoctors() {
  const [doctors, setDoctors] = useState([]);
  const [query, setQuery] = useState("");
  const [specialization, setSpecialization] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const { data } = await apiClient.get("/api/doctors", {
          params: specialization ? { specialization } : undefined,
        });
        if (!cancelled) setDoctors(data);
      } catch (err) {
        if (!cancelled) setError(apiError(err, "Could not load doctors."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [specialization]);

  const specializations = useMemo(() => {
    const values = new Set(doctors.map((item) => item.specialization).filter(Boolean));
    return [...values].sort();
  }, [doctors]);

  const visible = doctors.filter((doctor) => {
    const haystack = `${doctor.full_name} ${doctor.specialization} ${doctor.qualification || ""}`.toLowerCase();
    return haystack.includes(query.trim().toLowerCase());
  });

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold">Search doctors</h2>
        <p className="mt-1 text-sm text-stone-600">Filter by specialization, then open a profile to see availability.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Search by name">
          <input className={inputClass} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Doctor name" />
        </Field>
        <Field label="Specialization">
          <select className={inputClass} value={specialization} onChange={(e) => setSpecialization(e.target.value)}>
            <option value="">All specializations</option>
            {specializations.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {error ? <Alert>{error}</Alert> : null}
      {loading ? (
        <Spinner label="Loading doctors" />
      ) : visible.length === 0 ? (
        <EmptyState title="No doctors match" body="Try another name or specialization." />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {visible.map((doctor) => (
            <Link key={doctor.id} to={`/patient/doctors/${doctor.id}`}>
              <Card className="h-full hover:border-teal-700">
                <p className="text-lg font-semibold">{doctor.full_name}</p>
                <p className="text-sm text-teal-800">{doctor.specialization}</p>
                {doctor.qualification ? <p className="mt-2 text-sm text-stone-600">{doctor.qualification}</p> : null}
                <p className="mt-3 text-sm font-medium text-teal-800">View profile and availability →</p>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default PatientDoctors;
