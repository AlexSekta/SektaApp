import { useCallback, useEffect, useState } from "react";
import "./SyncSettings.css";

const API = `${window.location.protocol}//${window.location.hostname}:8000`;
type Item = {key:string;marketplace:string;label:string;connected:boolean;status:string;next_day:string|null;last_error:string|null;updated_at:string|null;first_day:string|null;last_day:string|null;loaded_days:number};
const fmtDay = (value:string|null) => value ? value.slice(0,10).split("-").reverse().join(".") : "—";
const fmtTime = (value:string|null) => value ? new Date(`${value.endsWith("Z")?value:value.replace(" ","T")}${/Z|[+]\d\d:\d\d$/.test(value)?"":"Z"}`).toLocaleString("ru-RU") : "—";
const labels:Record<string,string> = {running:"Загрузка истории",retry:"Повторная попытка",complete:"Завершено",unavailable:"Недоступно",pending:"Ожидает",not_started:"Не запускалась"};
export default function SyncSettings(){
  const [items,setItems] = useState<Item[]>([]);
  const [loading,setLoading] = useState(true);
  const [error,setError] = useState("");
  const refresh = useCallback(async()=>{
    try{
      const r = await fetch(`${API}/settings/sync-status`,{credentials:"include"});
      if(!r.ok) throw Error(`Не удалось получить статусы (${r.status})`);
      const data:{items:Item[]} = await r.json();
      setItems(data.items);setError("");
    }catch(e){setError(e instanceof Error?e.message:"Ошибка соединения");}
    finally{setLoading(false);}
  },[]);
  useEffect(()=>{void refresh();const id=window.setInterval(()=>void refresh(),60000);return()=>window.clearInterval(id);},[refresh]);
  return <section className="settings-section sync-settings">
    <div className="sync-settings-head"><div className="settings-section-heading"><h2>Синхронизация</h2><p>История продаж и состояние фоновых задач. Информация обновляется раз в минуту.</p></div><button type="button" className="sync-settings-refresh" onClick={()=>void refresh()}>Обновить</button></div>
    <h3>Продажи</h3>
    {loading?<p className="sync-settings-muted">Получаем данные…</p>:null}
    {error?<p className="sync-settings-error">{error}</p>:null}
    <div className="sync-settings-grid">{items.filter(i=>i.connected).map(i=><article className="sync-settings-card" key={i.key}>
      <div className="sync-settings-card-head"><strong>{i.label}</strong><span className={`sync-settings-state state-${i.status}`}>{labels[i.status]||i.status}</span></div>
      <div className="sync-settings-fields"><span>Загруженный период</span><b>{fmtDay(i.first_day)} — {fmtDay(i.last_day)}</b><span>Сохранено дней</span><b>{i.loaded_days.toLocaleString("ru-RU")}</b><span>Следующая дата истории</span><b>{fmtDay(i.next_day)}</b><span>Изменение статуса</span><b>{fmtTime(i.updated_at)}</b></div>
      {i.last_error?<div className="sync-settings-error-detail" title={i.last_error}>Ошибка: {i.last_error}</div>:null}
    </article>)}</div>
    {!loading&&!error&&!items.some(i=>i.connected)?<p className="sync-settings-muted">Нет подключённых маркетплейсов.</p>:null}
    <div className="sync-settings-future"><strong>Товары и остатки</strong><span>Здесь появятся статусы первичной загрузки каталогов и синхронизации остатков.</span></div>
  </section>;
}
