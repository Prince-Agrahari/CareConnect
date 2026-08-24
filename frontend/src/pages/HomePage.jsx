import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { portalHome } from "../lib/format.js";

function HomePage() {
  const { user } = useAuth();

  return (
    <main className="min-h-screen bg-[#f3efe6] text-stone-900">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16">
        <p className="text-sm font-semibold uppercase tracking-[0.25em] text-teal-800">CareConnect</p>
        <h1 className="mt-3 max-w-2xl text-5xl font-bold tracking-tight">Healthcare Appointment & Follow-up Manager</h1>
        <p className="mt-5 max-w-xl text-lg text-stone-600">
          Book visits, share symptoms, review prescriptions, and keep follow-up care in one place — for patients, doctors,
          and clinic admins.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          {user ? (
            <Link
              to={portalHome(user.role)}
              className="rounded-xl bg-teal-800 px-5 py-3 text-sm font-semibold text-white hover:bg-teal-900"
            >
              Open {user.role} portal
            </Link>
          ) : (
            <>
              <Link
                to="/login"
                className="rounded-xl bg-teal-800 px-5 py-3 text-sm font-semibold text-white hover:bg-teal-900"
              >
                Sign in
              </Link>
              <Link
                to="/register"
                className="rounded-xl bg-white px-5 py-3 text-sm font-semibold text-stone-800 ring-1 ring-stone-300 hover:bg-stone-50"
              >
                Register as a patient
              </Link>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

export default HomePage;
