import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "./AuthContext";
import "./Profile.css";

const API = `${window.location.protocol}//${window.location.hostname}:8000`;

async function send(url: string, body: object) {
  const response = await fetch(`${API}${url}`, { method: "PUT", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось сохранить изменения");
  return data;
}

export default function Profile() {
  const { user, refreshUser } = useAuth();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);

  useEffect(() => {
    const parts = (user?.name || "").trim().split(/\s+/);
    setFirstName(parts.shift() || "");
    setLastName(parts.join(" "));
    setEmail(user?.email || "");
  }, [user?.id, user?.name, user?.email]);

  const save = async (event: FormEvent) => {
    event.preventDefault(); setError(""); setMessage("");
    setSaving(true);
    try {
      await send("/auth/profile", { first_name: firstName.trim(), last_name: lastName.trim(), email: email.trim(), current_password: password });
      setPassword("");
      await refreshUser();
      setMessage("Данные профиля сохранены");
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить профиль"); }
    finally { setSaving(false); }
  };

  const changePassword = async (event: FormEvent) => {
    event.preventDefault(); setError(""); setMessage("");
    if (newPassword.length < 8) { setError("Новый пароль должен содержать минимум 8 символов"); return; }
    if (newPassword !== confirmPassword) { setError("Новые пароли не совпадают"); return; }
    setChangingPassword(true);
    try {
      const response = await fetch(`${API}/auth/change-password`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: oldPassword, new_password: newPassword }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Не удалось изменить пароль");
      setOldPassword(""); setNewPassword(""); setConfirmPassword("");
      setMessage("Пароль изменён");
    } catch (e) { setError(e instanceof Error ? e.message : "Ошибка смены пароля"); }
    finally { setChangingPassword(false); }
  };

  return <div className="profile-page">
    <header className="profile-header"><h1>Профиль</h1><p>Личные данные и безопасность вашей учётной записи.</p></header>
    {message && <div className="profile-notice profile-notice-success" role="status">{message}</div>}
    {error && <div className="profile-notice profile-notice-error" role="alert">{error}</div>}
    <section className="profile-card">
      <div className="profile-card-head"><h2>Личная информация</h2><p>Эти данные отображаются в меню и журнале действий сотрудников.</p></div>
      <form onSubmit={save}>
        <div className="profile-grid">
          <label className="profile-field">Имя<input value={firstName} onChange={e => setFirstName(e.target.value)} maxLength={120} required autoComplete="given-name" /></label>
          <label className="profile-field">Фамилия<input value={lastName} onChange={e => setLastName(e.target.value)} maxLength={120} autoComplete="family-name" /></label>
          <label className="profile-field profile-wide">Email<input type="email" value={email} onChange={e => setEmail(e.target.value)} maxLength={320} required autoComplete="email" /></label>
          {email.trim().toLowerCase() !== (user?.email || "").toLowerCase() && <label className="profile-field profile-wide">Текущий пароль для смены email<input type="password" value={password} onChange={e => setPassword(e.target.value)} required autoComplete="current-password" /><small>После сохранения новый email будет использоваться для входа. Подтверждение почты пока не настроено.</small></label>}
        </div>
        <button className="profile-button" disabled={saving}>{saving ? "Сохранение…" : "Сохранить изменения"}</button>
      </form>
    </section>
    <section className="profile-card"><div className="profile-card-head"><h2>Рабочее пространство</h2><p>Данные организации и текущие права.</p></div>
      <div className="profile-meta"><div><span>Организация</span><strong>{user?.organization_name || "—"}</strong></div><div><span>Роль</span><strong>{user?.role === "OWNER" ? "Владелец" : user?.role === "MEMBER" ? "Сотрудник" : user?.role || "—"}</strong></div></div>
    </section>
    <section className="profile-card"><div className="profile-card-head"><h2>Безопасность</h2><p>Смена пароля для текущего аккаунта.</p></div>
      <form onSubmit={changePassword}><div className="profile-grid">
        <label className="profile-field profile-wide">Текущий пароль<input type="password" value={oldPassword} onChange={e => setOldPassword(e.target.value)} required autoComplete="current-password" /></label>
        <label className="profile-field">Новый пароль<input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} minLength={8} required autoComplete="new-password" /></label>
        <label className="profile-field">Повторите новый пароль<input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} minLength={8} required autoComplete="new-password" /></label>
      </div><button className="profile-button" disabled={changingPassword}>{changingPassword ? "Сохранение…" : "Изменить пароль"}</button></form>
    </section>
  </div>;
}
