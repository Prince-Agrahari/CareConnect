import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { useAuth } from "./context/AuthContext.jsx";
import { GuestRoute, ProtectedRoute } from "./components/ProtectedRoute.jsx";
import { AdminLayout, DoctorLayout, PatientLayout } from "./components/Layout.jsx";
import { portalHome } from "./lib/format.js";
import HomePage from "./pages/HomePage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import RegisterPage from "./pages/RegisterPage.jsx";
import CalendarPage from "./pages/shared/CalendarPage.jsx";
import ProfilePage from "./pages/shared/ProfilePage.jsx";
import PatientDashboard from "./pages/patient/Dashboard.jsx";
import PatientDoctors from "./pages/patient/Doctors.jsx";
import DoctorProfile from "./pages/patient/DoctorProfile.jsx";
import BookAppointment from "./pages/patient/Book.jsx";
import PatientAppointments from "./pages/patient/Appointments.jsx";
import PatientAppointmentDetail from "./pages/patient/AppointmentDetail.jsx";
import RescheduleAppointment from "./pages/patient/Reschedule.jsx";
import MedicationReminders from "./pages/patient/Reminders.jsx";
import DoctorDashboard from "./pages/doctor/Dashboard.jsx";
import DoctorAppointments from "./pages/doctor/Appointments.jsx";
import DoctorAppointmentDetail from "./pages/doctor/AppointmentDetail.jsx";
import AdminDashboard from "./pages/admin/Dashboard.jsx";
import AdminDoctors from "./pages/admin/Doctors.jsx";
import DoctorForm from "./pages/admin/DoctorForm.jsx";
import AdminDoctorDetail from "./pages/admin/DoctorDetail.jsx";
import WorkingHoursPage from "./pages/admin/WorkingHours.jsx";
import LeavePage from "./pages/admin/Leave.jsx";
import AdminAppointments from "./pages/admin/Appointments.jsx";
import NotificationsPage from "./pages/admin/Notifications.jsx";

function CalendarRedirect() {
  const { user, loading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (loading) return;
    const params = new URLSearchParams(location.search);
    const calendar = params.get("calendar");
    if (!calendar || !user) return;
    navigate(`${portalHome(user.role)}/calendar${location.search}`, { replace: true });
  }, [loading, user, location.search, navigate]);

  return <HomePage />;
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<CalendarRedirect />} />
      <Route
        path="/login"
        element={
          <GuestRoute>
            <LoginPage />
          </GuestRoute>
        }
      />
      <Route
        path="/register"
        element={
          <GuestRoute>
            <RegisterPage />
          </GuestRoute>
        }
      />

      <Route
        path="/patient"
        element={
          <ProtectedRoute roles={["patient"]}>
            <PatientLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<PatientDashboard />} />
        <Route path="doctors" element={<PatientDoctors />} />
        <Route path="doctors/:doctorId" element={<DoctorProfile />} />
        <Route path="doctors/:doctorId/book" element={<BookAppointment />} />
        <Route path="appointments" element={<PatientAppointments />} />
        <Route path="appointments/:appointmentId" element={<PatientAppointmentDetail />} />
        <Route path="appointments/:appointmentId/reschedule" element={<RescheduleAppointment />} />
        <Route path="reminders" element={<MedicationReminders />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="profile" element={<ProfilePage />} />
      </Route>

      <Route
        path="/doctor"
        element={
          <ProtectedRoute roles={["doctor"]}>
            <DoctorLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<DoctorDashboard />} />
        <Route path="appointments" element={<DoctorAppointments />} />
        <Route path="appointments/:appointmentId" element={<DoctorAppointmentDetail />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="profile" element={<ProfilePage />} />
      </Route>

      <Route
        path="/admin"
        element={
          <ProtectedRoute roles={["admin"]}>
            <AdminLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<AdminDashboard />} />
        <Route path="doctors" element={<AdminDoctors />} />
        <Route path="doctors/new" element={<DoctorForm />} />
        <Route path="doctors/:doctorId" element={<AdminDoctorDetail />} />
        <Route path="doctors/:doctorId/edit" element={<DoctorForm />} />
        <Route path="doctors/:doctorId/hours" element={<WorkingHoursPage />} />
        <Route path="doctors/:doctorId/leave" element={<LeavePage />} />
        <Route path="appointments" element={<AdminAppointments />} />
        <Route path="notifications" element={<NotificationsPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
