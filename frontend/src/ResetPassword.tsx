import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "./AuthContext";
import "./Auth.css";

const API = `${window.location.protocol}//${window.location.hostname}:8000`;

export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) {
    return <Link to="/products">Перейти в приложение</Link>;
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");

    if (!token) {
      setError("Ссылка восстановления недействительна.");
      return;
    }

    if (password.length < 8) {
      setError("Пароль должен содержать минимум 8 символов.");
      return;
    }

    if (password !== confirmation) {
      setError("Пароли не совпадают.");
      return;
    }

    setBusy(true);

    try {
      const response = await fetch(`${API}/auth/password-reset/confirm`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          password,
        }),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : "Не удалось изменить пароль"
        );
      }

      navigate("/products", { replace: true });
      window.location.reload();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось изменить пароль"
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">MARKETPLACE ANALYTICS</div>
        <h1>Новый пароль</h1>
        <p className="auth-subtitle">
          Придумайте новый пароль. После изменения вы автоматически войдёте
          в аккаунт.
        </p>

        <form className="auth-form" onSubmit={submit}>
          <label>
            Новый пароль
            <input
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>

          <label>
            Повторите пароль
            <input
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              required
            />
          </label>

          {error && <div className="auth-error">{error}</div>}

          <button className="auth-button" disabled={busy}>
            {busy ? "Сохранение…" : "Сохранить новый пароль"}
          </button>
        </form>

        <div className="auth-switch">
          <Link to="/login">Вернуться ко входу</Link>
        </div>
      </div>
    </div>
  );
}
