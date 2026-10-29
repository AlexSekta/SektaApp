import { useCallback, useEffect, useRef, useState } from 'react';
import DateFilter from './DateFilter';

type Day = { day:string; date_from:string; date_to:string; status:string; row_count:number; total_amount:string; complete_days:number; expected_days:number; last_error:string|null };
type Group = { group:string; amount:string; operations:number };
type AccrualType = { group:string; kind:string; amount:string; operations:number };
type Article = { group:string; kind:string; article:string; product_name:string; amount:string; operations:number };
type ReportDetail = { day?:string; status:string; accrual_total:string; groups_total:string; balanced:boolean; unassigned_amount?:string; split_products?:number; groups:Group[]; types:AccrualType[]; articles:Article[]; note:string };
const API = `${window.location.protocol}//${window.location.hostname}:8000`;
const rub=(x:string|number)=>`${Number(x).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})} ₽`;
const displayGroupAmount=(value:string|number, category:string)=>rub(category==='Компенсации и декомпенсации'?value:Math.abs(Number(value)));
const ruDate=(v:string)=>/^\d{4}-\d{2}-\d{2}$/.test(v)?v.split('-').reverse().join('.'):v;
const iso=(d:Date)=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const now=new Date();
const defaults={from:iso(new Date(now.getFullYear(),now.getMonth(),1)),to:iso(now)};
const statusNames:Record<string,string>={complete:'Загружен',queued:'В очереди',retry:'Ошибка, повтор',loading:'Загружается'};
export default function OzonFinanceWeekly(){
 const [from,setFrom]=useState(defaults.from);
 const [to,setTo]=useState(defaults.to);
 const [days,setDays]=useState<Day[]>([]);
 const [selected,setSelected]=useState<string|null>(null);
 const [detail,setDetail]=useState<ReportDetail|null>(null);
 const [group,setGroup]=useState<string|null>(null);
 const [kind,setKind]=useState<string|null>(null);
 const [loading,setLoading]=useState(false);
 const [detailLoading,setDetailLoading]=useState(false);
 const [error,setError]=useState('');
 const detailRef=useRef<HTMLDivElement|null>(null);
 const load=useCallback(async()=>{
  if(!from||!to||to<from){setError('Проверьте диапазон дат');return;}
  setLoading(true);
  try{
   const response=await fetch(`${API}/analytics/ozon-finance/weeks?date_from=${from}&date_to=${to}`,{credentials:'include'});
   if(!response.ok)throw new Error(`HTTP ${response.status}`);
   const data=await response.json();
   setDays((data.items||[]).map((x:Day)=>({...x,day:x.date_from})));
   setSelected(previous=>(data.items||[]).some((d:Day)=>d.day===previous)?previous:null);
   setError('');
  }catch(e){setError(String(e));}finally{setLoading(false);}
 },[from,to]);
 useEffect(()=>{void load();},[load]);
 useEffect(()=>{
  if(!selected){setDetail(null);return;}
  let active=true;
  setDetailLoading(true);
  fetch(`${API}/analytics/ozon-finance/weeks/${selected}/reasons`,{credentials:'include'})
   .then(async r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();})
   .then(d=>{if(active){setDetail(d);setError('');}})
   .catch(e=>{if(active){setDetail(null);setError(String(e));}})
   .finally(()=>{if(active)setDetailLoading(false);});
  return()=>{active=false;};
 },[selected]);
 const selectDay=(day:string)=>{setSelected(old=>old===day?null:day);setGroup(null);setKind(null);
  requestAnimationFrame(()=>detailRef.current?.scrollIntoView({behavior:'smooth',block:'start'}));};
 const groupTypes=(detail?.types||[]).filter(t=>t.group===group);
 const articles=(detail?.articles||[]).filter(a=>a.group===group&&a.kind===kind);
 return <section className="wb-finance-section">
  <header className="wb-finance-section-header"><h2>Еженедельные отчёты Ozon</h2></header>
  <div className="wb-finance-filters">
   <label className="wb-finance-filter"><span>С</span><DateFilter value={from} onChange={setFrom}/></label>
   <label className="wb-finance-filter"><span>По</span><DateFilter value={to} onChange={setTo}/></label>
   <button className="wb-finance-refresh" type="button" disabled={loading} onClick={()=>void load()}>{loading?'Обновление…':'Обновить'}</button>
  </div>
  {error&&<p className="weekly-error" role="alert">{error}</p>}
  <div className="weekly-table-wrap"><table className="wb-finance-table"><thead><tr><th>Период отчёта</th><th>Операций</th><th>Итого начислений</th><th>Статус</th></tr></thead><tbody>
   {days.map(d=><tr key={d.day} className={selected===d.day?'selected':''} onClick={()=>selectDay(d.day)}><td>{ruDate(d.date_from)} — {ruDate(d.date_to)}</td><td>{d.row_count.toLocaleString('ru-RU')}</td><td>{rub(d.total_amount)}</td><td>{d.status==='partial'?`Загружается (${d.complete_days}/${d.expected_days} дн.)`:(statusNames[d.status]||d.status)}</td></tr>)}
   {!days.length&&<tr><td colSpan={4}>За выбранный период начислений пока нет.</td></tr>}
  </tbody></table></div>
  {selected&&<div ref={detailRef} className="weekly-detail"><h3>Начисления за неделю {ruDate(selected)}</h3>
   {detailLoading?<p>Загрузка детализации…</p>:detail&&<>
    {detail.status!=='complete'&&<p className="weekly-error">Данные за день загружаются — показатели предварительные.</p>}
    {!detail.balanced&&<p className="weekly-error">Расхождение между суммой групп и итогом дня!</p>}
    {detail.unassigned_amount && Number(detail.unassigned_amount)!==0 && <p className="weekly-error">Нераспределённый остаток: {rub(detail.unassigned_amount)}. Состав начислений требует дополнительной сверки с Ozon; итоговая сумма не изменена.</p>}
    <p className="weekly-note">Итого начислений Ozon: <strong>{rub(detail.accrual_total)}</strong>. Разбивка по услугам не вычитается второй раз.</p>
    <div className="wb-finance-metrics-grid">
     {detail.groups.map(g=><button key={g.group} className={`wb-finance-metric-card${group===g.group?' active':''}`} type="button" onClick={()=>{setGroup(v=>v===g.group?null:g.group);setKind(null);}}>
      <span className="wb-finance-metric-label">{g.group}</span><strong className="wb-finance-metric-value">{displayGroupAmount(g.amount,g.group)}</strong>
     </button>)}
    </div>
    {group&&<div className="wb-finance-breakdown"><h4>Обоснование оплаты — {group}</h4>
     <div className="weekly-table-wrap"><table className="wb-finance-table"><thead><tr><th>Тип начисления</th><th>Кол-во</th><th>Сумма</th></tr></thead><tbody>
      {groupTypes.map(t=><tr key={t.kind} className={kind===t.kind?'selected':''} onClick={()=>setKind(v=>v===t.kind?null:t.kind)}><td>{t.kind}</td><td>{t.operations.toLocaleString('ru-RU')}</td><td>{displayGroupAmount(t.amount,t.group)}</td></tr>)}
     </tbody></table></div>
    </div>}
    {group&&kind&&<div className="wb-finance-breakdown"><h4>{kind} — по артикулам</h4>
     <div className="weekly-table-wrap"><table className="wb-finance-table wb-finance-table--detail"><thead><tr><th>Описание</th><th>Артикул</th><th>Название товара</th><th>Кол-во</th><th>Сумма</th></tr></thead><tbody>
      {articles.map((a,i)=><tr key={`${a.article}:${i}`}><td>{a.kind}</td><td>{a.article||'—'}</td><td>{a.product_name||'—'}</td><td>{a.operations.toLocaleString('ru-RU')}</td><td>{displayGroupAmount(a.amount,a.group)}</td></tr>)}
      {!articles.length&&<tr><td colSpan={5}>Записей нет.</td></tr>}
     </tbody></table></div>
    </div>}
    <p className="weekly-note">{detail.note} «Кол-во» — число компонентов начисления, не уникальных товаров.</p>
   </>}
  </div>}
 </section>;
}
