import { useEffect, useState } from "react";
import { apiClient } from "../../api/client.js";
import { Alert, Spinner } from "../../components/ui.jsx";
import { apiError } from "../../lib/format.js";
import { AppointmentList, splitAppointments } from "./Dashboard.jsx";

function DoctorAppointments() {
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get("/api/appointments");
        setAppointments(data);
      } catch (err) {
        setError(apiError(err, "Could not load appointments."));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const { today, upcoming } = splitAppointments(appointments);
  const past = appointments
    .filter((item) => !today.includes(item) && !upcoming.includes(item))
    .sort((a, b) => new Date(b.start_datetime) - new Date(a.start_datetime));

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold">Appointments</h2>
      {error ? <Alert>{error}</Alert> : null}
      {loading ? (
        <Spinner label="Loading appointments" />
      ) : (
        <>
          <section>
            <h3 className="mb-3 font-semibold">Today</h3>
            <AppointmentList title="Today’s appointments" items={today} />
          </section>
          <section>
            <h3 className="mb-3 font-semibold">Upcoming</h3>
            <AppointmentList title="Upcoming appointments" items={upcoming} />
          </section>
          <section>
            <h3 className="mb-3 font-semibold">History</h3>
            <AppointmentList title="past appointments" items={past} />
          </section>
        </>
      )}
    </div>
  );
}

export default DoctorAppointments;
