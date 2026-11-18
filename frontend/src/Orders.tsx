import { useEffect, useMemo, useState } from 'react';
import DashboardPeriodPicker from './DashboardPeriodPicker';
import './Orders.css';

type Marketplace = 'OZON' | 'WB' | 'YANDEX';
type Group = 'all' | 'new' | 'assembly' | 'delivery';
type Item = {
  posting_number: string;
  order_number: string | null;
  status: string;
  status_group: string;
  scanit: string | null;
  upper_barcode: string | null;
  lower_barcode: string | null;
  first_seen_at: string;
  ozon_created_at: string | null;
  ready_detected_at: string | null;
  ready_from_new: boolean;
  sticker_saved_at: string | null;
  has_pdf: boolean;
};
type ApiResult = {
  marketplace: Marketplace;
  available: boolean;
  message?: string;
  items: Item[];
  total: number | null;
  counts: { new_count:number; assembly_count:number; delivery_count:number; all_count:number } | null;
};
const localDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const today = new Date();
const initialFrom = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 29);
const marketplaces: {key:Marketplace;title:string}[] = [{key:'WB',title:'WB'},{key:'OZON',title:'Ozon'},{key:'YANDEX',title:'ЯМаркет'}];
const groups: {key:Group;title:string}[] = [{key:'all',title:'Все'},{key:'new',title:'Новые'},{key:'assembly',title:'На сборке'},{key:'delivery',title:'В доставке'}];
const statusTitles: Record<string,string> = {
  awaiting_packaging: 'Ожидает сборки', awaiting_deliver: 'Ожидает отгрузки',
  delivering:'Доставляется', delivered:'Доставлен', cancelled:'Отменён',
  awaiting_registration:'Ожидает регистрации', acceptance_in_progress:'Принимается',
};
function base() {
  const dev = ['localhost','127.0.0.1'].includes(location.hostname) && location.port === '5173';
  return dev ? `${location.protocol}//${location.hostname}:8000` : `${location.origin}/api`;
}
export default function Orders(){
  const [marketplace,setMarketplace] = useState<Marketplace>('OZON');
  const [group,setGroup] = useState<Group>('all');
  const [from,setFrom] = useState(localDay(initialFrom));
  const [to,setTo] = useState(localDay(today));
  const [query,setQuery] = useState('');
  const [search,setSearch] = useState('');
  const [page,setPage] = useState(0);
  const [data,setData] = useState<ApiResult|null>(null);
  const [loading,setLoading] = useState(false);
  const [error,setError] = useState('');
  const [tick,setTick] = useState(0);
  const [settingsOpen,setSettingsOpen] = useState(false);
  const [delayMinutes,setDelayMinutes] = useState(20);
  const [autoCreate,setAutoCreate] = useState(false);
  const [settingsLoading,setSettingsLoading] = useState(false);
  const [settingsSaving,setSettingsSaving] = useState(false);
  const [settingsError,setSettingsError] = useState('');
  const [settingsInfo,setSettingsInfo] = useState('');
  useEffect(()=>{
    if (!settingsOpen || marketplace !== 'OZON') return;
    const ctrl=new AbortController();
    setSettingsLoading(true);setSettingsError('');setSettingsInfo('');
    fetch(`${base()}/orders/fbs/ozon/label-settings`,{credentials:'include',signal:ctrl.signal})
      .then(async r=>{if(!r.ok)throw Error(`Ошибка загрузки настроек: HTTP ${r.status}`);return r.json()})
      .then(v=>{setDelayMinutes(v.delay_minutes);setAutoCreate(v.auto_create_enabled)})
      .catch(e=>{if(!ctrl.signal.aborted)setSettingsError(String(e.message||e))})
      .finally(()=>{if(!ctrl.signal.aborted)setSettingsLoading(false)});
    return()=>ctrl.abort();
  },[settingsOpen,marketplace]);
  async function saveSettings(){
    setSettingsSaving(true);setSettingsError('');setSettingsInfo('');
    try{
      const res=await fetch(`${base()}/orders/fbs/ozon/label-settings`,{
        method:'PUT',credentials:'include',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({delay_minutes:delayMinutes,auto_create_enabled:autoCreate})
      });
      if(!res.ok)throw Error(`Ошибка сохранения: HTTP ${res.status}`);
      setSettingsInfo('Настройки сохранены');setTick(t=>t+1);
    }catch(e){setSettingsError(e instanceof Error?e.message:'Не удалось сохранить настройки')}
    finally{setSettingsSaving(false)}
  }
  const pageSize=50;
  useEffect(()=>{const id=window.setInterval(()=>setTick(x=>x+1),30000);return()=>window.clearInterval(id)},[]);
  useEffect(()=>{const id=window.setTimeout(()=>setSearch(query.trim()),350);return()=>window.clearTimeout(id)},[query]);
  useEffect(()=>setPage(0),[marketplace,group,from,to,search]);
  const params=useMemo(()=>new URLSearchParams({marketplace,status:group,date_from:from,date_to:to,q:search,limit:String(pageSize),offset:String(page*pageSize)}).toString(),[marketplace,group,from,to,search,page]);
  useEffect(()=>{
    const ac=new AbortController();
    setLoading(true);setError('');
    fetch(`${base()}/orders/fbs?${params}`,{credentials:'include',signal:ac.signal})
      .then(async r=>{if(!r.ok){const body=await r.json().catch(()=>({}));throw Error(typeof body.detail==='string'?body.detail:`Ошибка HTTP ${r.status}`)};return r.json() as Promise<ApiResult>})
      .then(setData)
      .catch(e=>{if(!ac.signal.aborted){setData(null);setError(e instanceof Error?e.message:'Не удалось загрузить заказы')}})
      .finally(()=>{if(!ac.signal.aborted)setLoading(false)});
    return()=>ac.abort();
  },[params,tick]);
  const counts=data?.counts;
  const total=data?.total??0;
  return <div className="fbs-orders-page">
    <div className="fbs-orders-heading"><div><h1>Заказы</h1><p>FBS · Архив заказов и этикеток</p></div><div className="fbs-orders-heading-actions">{marketplace==='OZON'&&<button type="button" className="fbs-orders-refresh" onClick={()=>setSettingsOpen(v=>!v)} aria-expanded={settingsOpen} aria-label="Настройки этикеток Ozon" title="Настройки этикеток Ozon">⚙ Настройки</button>}<button type="button" className="fbs-orders-refresh" onClick={()=>setTick(t=>t+1)} disabled={loading}>Обновить</button></div></div>
    {settingsOpen&&marketplace==='OZON'&&<section className="fbs-label-settings" aria-label="Настройки этикеток Ozon">
      <h2>Этикетки Ozon</h2>
      {settingsLoading?<p>Загрузка настроек…</p>:<>
        <label className="fbs-label-setting-field">Задержка после обнаружения перехода в «Готов к отгрузке», минут
          <input type="number" min={5} max={1440} step={1} value={delayMinutes} onChange={e=>setDelayMinutes(Number(e.target.value))}/>
        </label>
        <label className="fbs-label-setting-check"><input type="checkbox" checked={autoCreate} onChange={e=>setAutoCreate(e.target.checked)}/> Разрешить автоматическое создание PDF-заданий после задержки</label>
        <p className="fbs-label-settings-warning">Внимание: создание задания через API может изменить галочку этикетки в кабинете Ozon. Задержка не гарантирует фактическую печать. При выключенном PDF-мониторе настройка не запускает обработку. Для старых заказов без отслеженного перехода автоматическое создание недоступно.</p>
        <button className="fbs-orders-refresh" type="button" onClick={saveSettings} disabled={settingsSaving||!Number.isInteger(delayMinutes)||delayMinutes<5||delayMinutes>1440}>{settingsSaving?'Сохранение…':'Сохранить настройки'}</button>
      </>}
      {settingsError&&<p className="fbs-orders-error" role="alert">{settingsError}</p>}
      {settingsInfo&&<p role="status">{settingsInfo}</p>}
    </section>}
    <div className="fbs-orders-controls">
      <div className="fbs-orders-marketplaces" aria-label="Маркетплейс">{marketplaces.map(m=><button type="button" className={marketplace===m.key?'selected':''} key={m.key} onClick={()=>setMarketplace(m.key)} aria-pressed={marketplace===m.key}>{m.title}</button>)}</div>
      <div className="fbs-orders-statuses" aria-label="Статус">{groups.map(g=><button type="button" key={g.key} className={group===g.key?'selected':''} aria-pressed={group===g.key} onClick={()=>setGroup(g.key)}>{g.title}{g.key==='new'&&counts&&<span className="fbs-orders-count">{counts.new_count}</span>}{g.key==='assembly'&&counts&&<span className="fbs-orders-count">{counts.assembly_count}</span>}</button>)}</div>
      <div className="fbs-orders-filters"><DashboardPeriodPicker from={from} to={to} onChange={(a,b)=>{setFrom(a);setTo(b)}} label="Период обнаружения заказов"/>
      <div className="fbs-orders-search"><span aria-hidden="true">⌕</span><input value={query} maxLength={100} onChange={e=>setQuery(e.target.value)} placeholder="Номер заказа, отправления, этикетки..." aria-label="Поиск заказов"/>{query&&<button type="button" onClick={()=>setQuery('')} title="Очистить поиск" aria-label="Очистить поиск">×</button>}</div></div>
    </div>
    <p className="fbs-orders-note">Период фильтруется по дате первого обнаружения в SektaApp. Счётчики учитывают выбранный период и поиск. Данные обновляются без изменения статусов на маркетплейсах.</p>
    {error&&<div role="alert" className="fbs-orders-error">{error}</div>}
    {!error&&data&&!data.available&&<div className="fbs-orders-empty">{data.message}. Здесь появятся реальные заказы после подключения сборщика.</div>}
    {!error&&data?.available&&<>
      <div className="fbs-orders-summary">Найдено отправлений: <strong>{total.toLocaleString('ru-RU')}</strong>{loading&&<span> · Обновление...</span>}</div>
      <div className="fbs-orders-table-wrapper"><table className="fbs-orders-table"><colgroup><col/><col/><col className="fbs-orders-status-column"/><col/><col/></colgroup><thead><tr><th>Отправление</th><th>Номер заказа</th><th>Статус Ozon</th><th>Номер этикетки</th><th>Этикетка PDF</th></tr></thead><tbody>
      {data.items.map(item=><tr key={item.posting_number}><td className="fbs-orders-mono">{item.posting_number}</td><td className="fbs-orders-mono">{item.order_number||'—'}</td><td><span className={`fbs-orders-status fbs-orders-status-${item.status_group}`}>{statusTitles[item.status]||item.status}</span></td><td className="fbs-orders-mono">{item.scanit||'—'}</td><td>{item.has_pdf?<a className="fbs-orders-pdf" href={`${base()}/orders/fbs/ozon/${encodeURIComponent(item.posting_number)}/label`} target="_blank" rel="noopener noreferrer" title="Открыть сохранённый PDF для печати">Открыть PDF</a>:<span className="fbs-orders-unavailable">Не сохранена</span>}</td></tr>)}
      {!data.items.length&&<tr><td colSpan={5} className="fbs-orders-no-items">По выбранным фильтрам заказов нет</td></tr>}
      </tbody></table></div>
      <div className="fbs-orders-pagination"><button disabled={page===0||loading} onClick={()=>setPage(p=>p-1)}>Назад</button><span>{total?`${page*pageSize+1}–${Math.min((page+1)*pageSize,total)} из ${total}`:'0 заказов'}</span><button disabled={(page+1)*pageSize>=total||loading} onClick={()=>setPage(p=>p+1)}>Далее</button></div>
    </>}
    {!data&&!error&&loading&&<div className="fbs-orders-empty">Загрузка заказов...</div>}
  </div>
}
