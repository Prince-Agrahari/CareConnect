import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { Alert, Button, Field, inputClass } from "../components/ui.jsx";
import { apiError, portalHome } from "../lib/format.js";

function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function validate() {
    const next = {};
    if (!fullName.trim()) next.fullName = "Full name is required.";
    if (!email.trim()) next.email = "Email is required.";
    if (password.length < 8) next.password = "Password must be at least 8 characters.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    if (!validate()) return;
    setSubmitting(true);
    try {
      const user = await register({
        full_name: fullName.trim(),
        email: email.trim(),
        password,
      });
      navigate(portalHome(user.role), { replace: true, state: { notice: "Welcome to CareConnect." } });
    } catch (err) {
      setError(apiError(err, "Could not create that account."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f3efe6] px-4 py-16">
      <form onSubmit={onSubmit} className="mx-auto w-full max-w-md rounded-3xl bg-white p-8 shadow-sm ring-1 ring-stone-200">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-800">CareConnect</p>
        <h1 className="mt-2 text-2xl font-semibold">Patient registration</h1>
        <p className="mt-1 text-sm text-stone-600">Doctor and admin accounts are created by clinic administrators.</p>
        {error ? (
          <div className="mt-4">
            <Alert>{error}</Alert>
          </div>
        ) : null}
        <div className="mt-6 space-y-4">
          <Field label="Full name" error={errors.fullName}>
            <input className={inputClass} value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Email" error={errors.email}>
            <input className={inputClass} type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </Field>
          <Field label="Password" error={errors.password}>
            <input className={inputClass} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          </Field>
        </div>
        <Button type="submit" className="mt-6 w-full" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </Button>
        <p className="mt-4 text-center text-sm text-stone-600">
          Already registered?{" "}
          <Link className="font-semibold text-teal-800" to="/login">
            Sign in
          </Link>
        </p>
      </form>
    </main>
  );
}

export default RegisterPage;
