import { useEffect, useRef, useState } from 'react';
import './UnifiedSales.css';

const dateString = (d: Date) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const shortDate = (s: string) => new Date(`${s}T12:00:00`).toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit',year:'numeric'});
const addDays = (d: Date, n: number) => {const r=new Date(d);r.setDate(r.getDate()+n);return r;};
const monthDays = (y:number,m:number) => new Date(y,m+1,0).getDate();

type Props = {from:string;to:string;onChange:(from:string,to:string)=>void;label?:string};
export default function DashboardPeriodPicker({from,to,onChange,label='Выбрать период'}:Props){
 const ref=useRef<HTMLDivElement>(null);
 const [open,setOpen]=useState(false);
 const [cursor,setCursor]=useState(()=>{const d=new Date();return new Date(d.getFullYear(),d.getMonth(),1)});
 const [draft,setDraft]=useState<string|null>(null);
 useEffect(()=>{
  if(!open)return;
  const close=(e:MouseEvent)=>{if(ref.current&&!ref.current.contains(e.target as Node)){setOpen(false);setDraft(null)}};
  document.addEventListener('mousedown',close);return()=>document.removeEventListener('mousedown',close)
 },[open]);
 const choose=(value:string)=>{
  if(!draft){setDraft(value);return}
  let a=draft,b=value;if(a>b)[a,b]=[b,a];
  if((Date.parse(b)-Date.parse(a))/86400000>365){setDraft(value);return}
  onChange(a,b);setDraft(null);setOpen(false);
 };
 const preset=(key:string)=>{
  const now=new Date();now.setHours(12,0,0,0);
  let start=now,end=now;
  if(key==='yesterday')start=end=addDays(now,-1);
  if(key==='7')start=addDays(now,-6);
  if(key==='14')start=addDays(now,-13);
  if(key==='month')start=new Date(now.getFullYear(),now.getMonth(),1,12);
  if(key==='year')start=new Date(now.getFullYear(),0,1,12);
  onChange(dateString(start),dateString(end));setDraft(null);setOpen(false)
 };
 const offset=(cursor.getDay()+6)%7;
 const days=monthDays(cursor.getFullYear(),cursor.getMonth());
 const cells=Array.from({length:Math.ceil((offset+days)/7)*7},(_,i)=>{
  const d=i-offset+1;return d>0&&d<=days?dateString(new Date(cursor.getFullYear(),cursor.getMonth(),d,12)):null
 });
 return <div className="unified-range-wrap" ref={ref}>
  <button type="button" className="unified-range-trigger" aria-label={label} aria-expanded={open} onClick={()=>{setOpen(v=>!v);setDraft(null)}}>
   <svg className="unified-calendar-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8"/><path d="M7 3v4M17 3v4M3 10h18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
   {shortDate(from)} — {shortDate(to)}
  </button>
  {open&&<div className="unified-calendar" role="dialog" aria-label={label}>
   <div className="unified-presets">{[['today','Сегодня'],['yesterday','Вчера'],['7','7 дней'],['14','14 дней'],['month','Месяц'],['year','Год']].map(([key,title])=><button key={key} type="button" onClick={()=>preset(key)}>{title}</button>)}</div>
   <div className="unified-calendar-main"><div className="unified-cal-header">
    <button type="button" aria-label="Предыдущий месяц" onClick={()=>setCursor(new Date(cursor.getFullYear(),cursor.getMonth()-1,1))}>‹</button>
    <b>{cursor.toLocaleDateString('ru-RU',{month:'long',year:'numeric'})}</b>
    <button type="button" aria-label="Следующий месяц" onClick={()=>setCursor(new Date(cursor.getFullYear(),cursor.getMonth()+1,1))}>›</button>
   </div><div className="unified-cal-grid">{['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(d=><span className="unified-cal-weekday" key={d}>{d}</span>)}
   {cells.map((d,i)=>d?<button type="button" key={d} className={[(d===draft||(!draft&&(d===from||d===to)))?'edge':'',(!draft&&d>from&&d<to)?'between':''].join(' ')} onClick={()=>choose(d)}>{Number(d.slice(-2))}</button>:<span key={`blank-${i}`}/>)}
   </div><p>{draft?`Начало: ${shortDate(draft)}. Выберите конец (можно ту же дату).`:'Выберите первую и последнюю дату периода'}</p></div>
  </div>}
 </div>
}
