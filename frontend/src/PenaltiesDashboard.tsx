import { useEffect, useMemo, useState } from 'react';
import DateFilter from './DateFilter';
import './PenaltiesDashboard.css';
import { downloadWorkbook } from './ExcelDownload';
import './Reviews.css';

type Marketplace = 'WB' | 'OZON' | 'YANDEX';
type Item = { description: string; sku: string; quantity: number; amount: number };
type Reason = { reason: string; quantity: number; amount: number; items: Item[] };
type MarketData = { available: boolean; total: number | null; reasons: Reason[]; message?: string; report_statuses?: Record<string, number> };
type Data = { marketplaces: Record<Marketplace, MarketData>; note: string };
const names: Record<Marketplace, string> = { WB: 'WB', OZON: 'Ozon', YANDEX: 'Я.Маркет' };
const all: Marketplace[] = ['WB', 'OZON', 'YANDEX'];
const API = `${window.location.protocol}//${window.location.hostname}:8000`;
const money = (v: number) => `${v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽`;
function dayISO(d: Date) { return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function dates() { const d = new Date(); return { from: dayISO(new Date(d.getFullYear(),d.getMonth(),1)), to: dayISO(d) }; }

export default function PenaltiesDashboard() {
  const initial = useMemo(dates, []);
  const [from,setFrom] = useState(initial.from);
  const [to,setTo] = useState(initial.to);
  const [selected,setSelected] = useState<Marketplace[]>(all);
  const [openMarket,setOpenMarket] = useState<Marketplace|null>(null);
  const [openReason,setOpenReason] = useState<string|null>(null);
  const [data,setData] = useState<Data|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const valid = Boolean(from && to && from <= to && (new Date(to).getTime()-new Date(from).getTime())<=366*86400000);
  useEffect(() => {
    if (!valid) return;
    const controller = new AbortController();
    setBusy(true);
    fetch(`${API}/analytics/penalties-breakdown?date_from=${from}&date_to=${to}`, { credentials: 'include', signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
      .then((result:Data) => { setData(result); setError(''); })
      .catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  },[from,to,valid]);
  const isAll = selected.length === 3;
  const active = openMarket && selected.includes(openMarket) ? openMarket : null;
  const activePenalties = selected.map(m => data?.marketplaces[m]).filter((m): m is MarketData => Boolean(m?.available && m.total !== null));
  const penaltiesTotal = activePenalties.reduce((sum, m) => sum + (m.total ?? 0), 0);
  const penaltiesPartial = selected.some(m => !data?.marketplaces[m]?.available || data?.marketplaces[m]?.total === null);
  const market = active ? data?.marketplaces[active] : null;
  function select(m:Marketplace) {
    setSelected(prev => prev.length === 3 ? [m] : prev.includes(m) ? (prev.length === 1 ? prev : prev.filter(p => p!==m)) : all.filter(p => prev.includes(p)||p===m));
    setOpenMarket(null);setOpenReason(null);
  }
  function toggleMarket(m:Marketplace) {setOpenMarket(prev=>prev===m?null:m);setOpenReason(null);}
  function exportPenalties() {
    if (!data) return;
    const reasons: Array<Array<string | number | null>> = [];
    const articles: Array<Array<string | number | null>> = [];
    selected.forEach(m => {
      const details = data.marketplaces[m];
      if (!details?.available) {
        reasons.push([names[m], from, to, 'Данные недоступны', '', '']);
        articles.push([names[m], from, to, 'Данные недоступны', '', '', '']);
        return;
      }
      details.reasons.forEach(r => {
        reasons.push([names[m], from, to, r.reason, r.quantity, r.amount]);
        r.items.forEach(item => articles.push([names[m], from, to, r.reason, item.sku || '', item.quantity, item.amount]));
      });
    });
    downloadWorkbook(`Штрафы_${from}_${to}.xlsx`, [
      { name: 'Причины штрафов', headers: ['Маркетплейс','С','По','Описание штрафа','Кол-во','Сумма, ₽'], rows: reasons, widths: [16,14,14,58,14,20] },
      { name: 'По артикулам', headers: ['Маркетплейс','С','По','Описание','Артикул','Кол-во','Сумма, ₽'], rows: articles, widths: [16,14,14,58,20,14,20] }
    ]);
  }
  const incompletes = (data?.marketplaces.WB.report_statuses || {});
  const pending = (incompletes.queued || 0) + (incompletes.loading || 0) + (incompletes.retry || 0) + (incompletes.mismatch || 0);
  return <section className="penalty-dash">
    <div className="penalty-head"><h2>Штрафы за период</h2><span>Даты финансовых отчётов</span></div>
    <div className="penalty-filters">
      <div className="penalty-date"><span>С</span><DateFilter value={from} onChange={setFrom} ariaLabel="Начало периода штрафов" /></div>
      <div className="penalty-date"><span>По</span><DateFilter value={to} onChange={setTo} ariaLabel="Конец периода штрафов" /></div>
      <div className="penalty-picks">
        <button type="button" className={isAll?'active':''} onClick={()=>{setSelected(all);setOpenMarket(null);setOpenReason(null);}}>Все</button>
        {all.map(m=><button key={m} type="button" className={!isAll && selected.includes(m)?'active':''} onClick={()=>select(m)}>{names[m]}</button>)}
      </div>
    </div>
    {!valid && <p role="alert" className="penalty-error">Укажите период не больше 367 дней, с датой начала не позже окончания.</p>}
    {error && <p role="alert" className="penalty-error">Не удалось загрузить штрафы: {error}</p>}
    <div className="penalty-cards penalty-cards-with-total">
      <div className="penalty-card penalty-card-total" aria-label="Сумма штрафов по выбранным маркетплейсам">
        <span>Все · сумма выбранных</span>
        <strong>{!data ? '—' : activePenalties.length ? money(penaltiesTotal) : 'Нет данных'}</strong>
        <small>{penaltiesPartial ? 'Частичная сумма: не все МП подключены' : 'Все выбранные МП'}</small>
      </div>
      {all.filter(m=>selected.includes(m)).map(m=>{
        const item=data?.marketplaces[m];return <button type="button" key={m} className={`penalty-card ${active===m?'active':''}`} onClick={()=>toggleMarket(m)}>
          <span>{names[m]}</span><strong>{item?.available ? money(item.total||0) : 'Нет данных'}</strong>
          <small>{item?.available?'Посмотреть детализацию':'Источник ещё не подключён'}</small>
        </button>;
      })}
    </div>
    {busy && <p className="penalty-note">Обновление данных…</p>}
    {pending>0 && selected.includes('WB') && <p className="penalty-note">WB: {pending} отчётов за период ещё не сверены или ожидают загрузки. Сумма может измениться.</p>}
    {active && market && <div className="penalty-details">
      <div className="penalty-details-heading">
        <h3>Детализация штрафов — {names[active]}</h3>
        <button type="button" className="dashboard-xlsx-button" onClick={exportPenalties} disabled={busy || !valid || !data}>Скачать Excel</button>
      </div>
      {!market.available ? <p className="penalty-note">{market.message}</p> : <>
        <div className="penalty-table-wrap"><table><thead><tr><th>Описание штрафа</th><th>Кол-во</th><th>Сумма</th></tr></thead><tbody>
          {market.reasons.map(r=><tr key={r.reason} className={openReason===r.reason?'active':''} onClick={()=>setOpenReason(prev=>prev===r.reason?null:r.reason)} tabIndex={0} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setOpenReason(prev=>prev===r.reason?null:r.reason)}}}>
            <td>{r.reason}</td><td>{r.quantity.toLocaleString('ru-RU')}</td><td>{money(r.amount)}</td>
          </tr>)}
          {!market.reasons.length&&<tr><td colSpan={3}>За выбранный период штрафов в загруженных отчётах нет.</td></tr>}
        </tbody></table></div>
        {openReason && market.reasons.some(r=>r.reason===openReason) && <div className="penalty-items">
          <h4>{openReason}</h4><div className="penalty-table-wrap"><table><thead><tr><th>Описание</th><th>Артикул</th><th>Кол-во</th><th>Сумма</th></tr></thead><tbody>
          {market.reasons.find(r=>r.reason===openReason)?.items.map((item,i)=><tr key={`${item.sku}-${i}`}><td>{item.description}</td><td>{item.sku||''}</td><td>{item.quantity.toLocaleString('ru-RU')}</td><td>{money(item.amount)}</td></tr>)}
          </tbody></table></div>
        </div>}
      </>}
    </div>}
    <p className="penalty-foot">Штрафы WB считаются только из ежедневных финансовых отчётов, без дублирования недельных. «Кол-во» — число записей по штрафам, не уникальных артикулов.</p>
  </section>;
}
