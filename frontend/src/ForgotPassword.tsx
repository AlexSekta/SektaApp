import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import "./Auth.css";

const API = `${window.location.protocol}//${window.location.hostname}:8000`;

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setMessage("");
    setBusy(true);

    try {
      const response = await fetch(`${API}/auth/password-reset/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : "Не удалось отправить запрос"
        );
      }

      setMessage(
        data.message ||
        "Если аккаунт с этим email существует, мы отправили письмо."
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось отправить запрос"
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">MARKETPLACE ANALYTICS</div>
        <h1>Восстановление пароля</h1>
        <p className="auth-subtitle">
          Введите email, указанный при регистрации. Если аккаунт существует,
          мы отправим ссылку для создания нового пароля.
        </p>

        <form className="auth-form" onSubmit={submit}>
          <label>
            Email
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>

          {error && <div className="auth-error">{error}</div>}
          {message && <div className="auth-success">{message}</div>}

          <button className="auth-button" disabled={busy}>
            {busy ? "Отправка…" : "Отправить ссылку"}
          </button>
        </form>

        <div className="auth-switch">
          <Link to="/login">Вернуться ко входу</Link>
        </div>
      </div>
    </div>
  );
}
