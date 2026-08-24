import { useLocation } from "react-router-dom";
import { useAuth } from "../../context/AuthContext.jsx";
import { Alert, Card } from "../../components/ui.jsx";

function ProfilePage() {
  const { user } = useAuth();
  const notice = useLocation().state?.notice;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold">Profile</h2>
        <p className="mt-1 text-sm text-stone-600">Account details come from the server. Role and access are not decided in the browser.</p>
      </div>
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      <Card className="max-w-lg space-y-3">
        <Row label="Name" value={user?.full_name} />
        <Row label="Email" value={user?.email} />
        <Row label="Role" value={user?.role} />
        <Row label="Status" value={user?.is_active ? "Active" : "Inactive"} />
      </Card>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">{label}</p>
      <p className="mt-0.5 capitalize">{value || "—"}</p>
    </div>
  );
}

export default ProfilePage;
