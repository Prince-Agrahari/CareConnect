import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { Button } from "./ui.jsx";

function Shell({ title, links, children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-[#f3efe6] text-stone-900">
      <header className="border-b border-stone-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-800">CareConnect</p>
            <h1 className="text-lg font-semibold">{title}</h1>
          </div>
          <div className="flex items-center gap-3">
            <p className="hidden text-sm text-stone-600 sm:block">{user?.full_name}</p>
            <Button
              variant="secondary"
              onClick={() => {
                logout();
                navigate("/login");
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 pb-3">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium ${
                  isActive ? "bg-teal-800 text-white" : "text-stone-600 hover:bg-stone-100"
                }`
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children || <Outlet />}</main>
    </div>
  );
}

export function PatientLayout() {
  return (
    <Shell
      title="Patient portal"
      links={[
        { to: "/patient", label: "Dashboard", end: true },
        { to: "/patient/doctors", label: "Find a doctor" },
        { to: "/patient/appointments", label: "Appointments" },
        { to: "/patient/reminders", label: "Reminders" },
        { to: "/patient/calendar", label: "Calendar" },
        { to: "/patient/profile", label: "Profile" },
      ]}
    />
  );
}

export function DoctorLayout() {
  return (
    <Shell
      title="Doctor portal"
      links={[
        { to: "/doctor", label: "Dashboard", end: true },
        { to: "/doctor/appointments", label: "Appointments" },
        { to: "/doctor/calendar", label: "Calendar" },
        { to: "/doctor/profile", label: "Profile" },
      ]}
    />
  );
}

export function AdminLayout() {
  return (
    <Shell
      title="Admin portal"
      links={[
        { to: "/admin", label: "Dashboard", end: true },
        { to: "/admin/doctors", label: "Doctors" },
        { to: "/admin/appointments", label: "Appointments" },
        { to: "/admin/notifications", label: "Notifications" },
      ]}
    />
  );
}
