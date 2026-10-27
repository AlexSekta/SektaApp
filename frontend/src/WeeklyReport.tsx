import { useCallback, useEffect, useState } from 'react';
import './Analytics.css';
import './WeeklyReport.css';
type Report = {report_id:number;date_from:string;date_to:string;expected_penalty:string;expected_deduction:string;penalty:string;deduction:string;status:string;loaded_rows:number;last_error:string|null;updated_at:string};
type Product = {identifier:string;operations:number;penalty:string;deduction:string};
type Group = {kind:string;reason:string;attribution:string;rows:number;amount:string};
const rub=(v:string|number)=>`${Number(v).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})} ₽`;
const api=`${window.location.protocol}//${window.location.hostname}:8000`;
const status:Record<string,string>={queued:'В очереди',loading:'Загружается',retry:'Повтор запроса',complete:'Сверено',mismatch:'Расхождение'};
type Daily = {report_id:number;report_date:string;report_type:number;status:string;loaded_rows:number;last_error:string|null;
 retail:string;for_pay:string;commission:string;vat:string;acquiring:string;logistics:string;storage:string;acceptance:string;
 penalty:string;deduction:string;additional_payment:string;expected_bank_payment:string};
type DailyReason = {reason:string;operation:string;attribution:string;rows:number;penalty:string;deduction:string;logistics:string;storage:string;acceptance:string};
export default function WeeklyReport(){
 const [mode,setMode]=useState<'daily'|'weekly'>('daily');
 const [dayFrom,setDayFrom]=useState(()=>{const d=new Date();d.setDate(d.getDate()-7);return d.toLocaleDateString('en-CA')});
 const [dayTo,setDayTo]=useState(()=>{const d=new Date();d.setDate(d.getDate()-1);return d.toLocaleDateString('en-CA')});
 const [daily,setDaily]=useState<Daily[]>([]);
 const [dailySelected,setDailySelected]=useState<number|null>(null);
 const [dailyReasons,setDailyReasons]=useState<DailyReason[]>([]);
 const [reports,setReports]=useState<Report[]>([]);
 const [selected,setSelected]=useState<number|null>(null);
 const [groups,setGroups]=useState<Group[]>([]);
 const [products,setProducts]=useState<Product[]>([]);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const load=useCallback(async()=>{try{const r=await fetch(`${api}/analytics/wb-finance/reports`,{credentials:'include'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const data=await r.json();setReports(data.items||[]);}catch(e){setError(String(e));}},[]);
 useEffect(()=>{void load();const timer=setInterval(()=>void load(),60000);return()=>clearInterval(timer)},[load]);
 useEffect(()=>{if(selected===null){setGroups([]);setProducts([]);return;}let alive=true;setBusy(true);fetch(`${api}/analytics/wb-finance/reports/${selected}`,{credentials:'include'}).then(async r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()}).then(d=>{if(alive){setGroups(d.groups||[]);setError('');void fetch(`${api}/analytics/wb-finance/reports/${selected}/products`,{credentials:'include'}).then(r=>r.json()).then(p=>{if(alive)setProducts(p.items||[])}).catch(()=>{})}}).catch(e=>{if(alive)setError(String(e))}).finally(()=>{if(alive)setBusy(false)});return()=>{alive=false}},[selected]);
 useEffect(()=>{if(mode!=='daily'||!dayFrom||!dayTo||dayFrom>dayTo)return;let active=true;
 const loadDaily=()=>fetch(`${api}/analytics/wb-finance/daily?date_from=${dayFrom}&date_to=${dayTo}`,{credentials:'include'})
 .then(async r=>{if(!r.ok)throw Error(`HTTP ${r.status}`);return r.json()})
 .then(d=>{if(active)setDaily(d.items||[])}) .catch(e=>{if(active)setError(String(e))});
 void loadDaily();const timer=setInterval(()=>void loadDaily(),60000);
 return()=>{active=false;clearInterval(timer)}},[mode,dayFrom,dayTo]);
 useEffect(()=>{if(dailySelected===null)return;let active=true;
 fetch(`${api}/analytics/wb-finance/daily/${dailySelected}/reasons`,{credentials:'include'})
 .then(r=>r.json()).then(d=>{if(active)setDailyReasons(d.items||[])})
 .catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[dailySelected]);
 const dailyReport=daily.find(r=>r.report_id===dailySelected);
 const detail=reports.find(r=>r.report_id===selected);
 return <div className="analytics-page"><div className="analytics-header"><div><h1>Финансовые отчёты</h1><p>Ежедневный оперативный контроль и недельная финансовая сверка Wildberries.</p></div></div>
 <div className="weekly-mode"><button className={mode==='daily'?'active':''} onClick={()=>setMode('daily')}>Ежедневные</button><button className={mode==='weekly'?'active':''} onClick={()=>setMode('weekly')}>Еженедельные</button></div>
 {mode==='daily'&&<section className="weekly-finance"><header><h2>Ежедневные отчёты WB</h2><span>Даты финансовых отчётов, не даты заказов</span></header>
 <div className="weekly-dates"><label>С <input type="date" value={dayFrom} onChange={e=>setDayFrom(e.target.value)}/></label><label>По <input type="date" value={dayTo} onChange={e=>setDayTo(e.target.value)}/></label></div>
 {error&&<p role="alert" className="weekly-error">{error}</p>}
 {!daily.length?<p>За выбранный период пока нет отчётов. Ежедневная загрузка выполняется фоново после формирования отчёта WB.</p>:<div className="weekly-table-wrap"><table><thead><tr><th>Дата отчёта</th><th>Тип</th><th>Реализация</th><th>К перечислению за товар</th><th>Штрафы</th><th>Удержания</th><th>Статус</th></tr></thead><tbody>{daily.map(r=><tr key={r.report_id} className={dailySelected===r.report_id?'selected':''} onClick={()=>setDailySelected(r.report_id)}><td>{r.report_date}</td><td>{r.report_type===2?'По выкупам':'Основной'}</td><td>{rub(r.retail)}</td><td>{rub(r.for_pay)}</td><td>{rub(r.penalty)}</td><td>{rub(r.deduction)}</td><td>{status[r.status]||r.status}</td></tr>)}</tbody></table></div>}
 {dailyReport&&<div className="weekly-detail"><h3>Отчёт №{dailyReport.report_id} · {dailyReport.report_type===2?'По выкупам':'Основной'}</h3>
 {dailyReport.status!=='complete'&&<p className="weekly-error">Суммы предварительные: полная сверка пока не завершена. Банковский итог взят из сводки WB.</p>}
 <div className="weekly-daily-summary">{[
 ['Реализация',dailyReport.retail],['Комиссия WB без НДС',dailyReport.commission],['НДС на комиссию',dailyReport.vat],['Эквайринг',dailyReport.acquiring],['К перечислению за товар',dailyReport.for_pay],['Логистика',dailyReport.logistics],['Хранение',dailyReport.storage],['Платная приёмка',dailyReport.acceptance],['Штрафы',dailyReport.penalty],['Удержания',dailyReport.deduction],['Доплаты',dailyReport.additional_payment],['Итого к оплате (сводка WB)',dailyReport.expected_bank_payment]
 ].map(([label,value])=><div key={label}><span>{label}</span><strong>{rub(value)}</strong></div>)}</div>
 <h3>Обоснования расходов (до 250 групп)</h3><div className="weekly-table-wrap"><table><thead><tr><th>Основание</th><th>Привязка</th><th>Строк</th><th>Логистика</th><th>Штрафы</th><th>Удержания</th></tr></thead><tbody>{dailyReasons.map((r,i)=><tr key={i}><td>{r.reason}</td><td>{r.attribution==='sku_candidate'?'Кандидат на SKU':'Общий / без SKU'}</td><td>{r.rows}</td><td>{rub(r.logistics)}</td><td>{rub(r.penalty)}</td><td>{rub(r.deduction)}</td></tr>)}</tbody></table></div>
 <p className="weekly-note">Обязательства по ежедневным отчётам предварительные. Типы отчётов отображаются отдельно; их нельзя складывать с недельными итогами. Наличие SKU не гарантирует корректное отнесение расходов на товар.</p>
 </div>}</section>}
 {mode==='weekly'&&<>
 <section className="weekly-finance"><header><h2>Отчёты WB</h2><button onClick={()=>void load()}>Обновить</button></header>
 {error&&<p role="alert" className="weekly-error">{error}</p>}
 {!reports.length?<p>Отчёты ещё не загружены. Фоновая загрузка начнётся после запуска backend; статус обновляется автоматически.</p>:
 <div className="weekly-table-wrap"><table><thead><tr><th>Неделя</th><th>Отчёт</th><th>Штрафы</th><th>Удержания</th><th>Статус</th></tr></thead><tbody>{reports.map(r=><tr key={r.report_id} className={selected===r.report_id?'selected':''} onClick={()=>setSelected(r.report_id)}><td>{r.date_from} — {r.date_to}</td><td>{r.report_id}</td><td>{rub(r.penalty)} / {rub(r.expected_penalty)}</td><td>{rub(r.deduction)} / {rub(r.expected_deduction)}</td><td>{status[r.status]||r.status}</td></tr>)}</tbody></table></div>}
 {detail&&<div className="weekly-detail"><h3>Отчёт №{detail.report_id}</h3><p>Строк: {detail.loaded_rows.toLocaleString('ru-RU')} · {status[detail.status]||detail.status}. {detail.last_error||''}</p>
 {detail.status!=='complete'&&<p className="weekly-error">Данные предварительные, финансовая сверка ещё не подтверждена.</p>}
 {busy?<p>Загрузка детализации…</p>:<div className="weekly-table-wrap"><table><thead><tr><th>Тип</th><th>Причина</th><th>Привязка</th><th>Операций</th><th>Сумма</th></tr></thead><tbody>{groups.map((g,i)=><tr key={i}><td>{g.kind}</td><td>{g.reason}</td><td>{g.attribution==='product_candidate'?'Кандидат на SKU':'Нет идентификатора товара'}</td><td>{g.rows}</td><td>{rub(g.amount)}</td></tr>)}</tbody></table></div>}
 <h3>Потоварная сводка штрафов и удержаний (до 500 SKU)</h3><div className="weekly-table-wrap"><table><thead><tr><th>Артикул / nmId</th><th>Операций</th><th>Штрафы</th><th>Удержания</th></tr></thead><tbody>{products.map((p,i)=><tr key={i}><td>{p.identifier}</td><td>{p.operations}</td><td>{rub(p.penalty)}</td><td>{rub(p.deduction)}</td></tr>)}</tbody></table></div><p className="weekly-note">Наличие nmId / vendorCode — только предварительная возможность привязки. Общие расходы и окончательное распределение по товарам будут утверждаться отдельно. Эти суммы пока не влияют на юнит-экономику.</p></div>}
 </section></>}</div>;
}
