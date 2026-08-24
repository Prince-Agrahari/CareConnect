import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { Alert, Button, Field, inputClass } from "../components/ui.jsx";
import { apiError, portalHome } from "../lib/format.js";

function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function validate() {
    const next = {};
    if (!email.trim()) next.email = "Email is required.";
    if (!password) next.password = "Password is required.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    if (!validate()) return;
    setSubmitting(true);
    try {
      const user = await login(email.trim(), password);
      const dest = location.state?.from || portalHome(user.role);
      navigate(dest, { replace: true });
    } catch (err) {
      setError(apiError(err, "Incorrect email or password."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f3efe6] px-4 py-16">
      <form onSubmit={onSubmit} className="mx-auto w-full max-w-md rounded-3xl bg-white p-8 shadow-sm ring-1 ring-stone-200">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-800">CareConnect</p>
        <h1 className="mt-2 text-2xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-stone-600">Patients, doctors, and admins use the same sign-in. Your portal is chosen by the server.</p>
        {error ? (
          <div className="mt-4">
            <Alert>{error}</Alert>
          </div>
        ) : null}
        <div className="mt-6 space-y-4">
          <Field label="Email" error={errors.email}>
            <input className={inputClass} type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </Field>
          <Field label="Password" error={errors.password}>
            <input className={inputClass} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </Field>
        </div>
        <Button type="submit" className="mt-6 w-full" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
        <p className="mt-4 text-center text-sm text-stone-600">
          New patient?{" "}
          <Link className="font-semibold text-teal-800" to="/register">
            Create an account
          </Link>
        </p>
      </form>
    </main>
  );
}

export default LoginPage;
