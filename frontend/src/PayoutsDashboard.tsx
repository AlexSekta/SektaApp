import { useEffect, useMemo, useState } from 'react';
import DashboardPeriodPicker from './DashboardPeriodPicker';
import './PayoutsDashboard.css';
import './Reviews.css';

type Marketplace = 'WB' | 'OZON' | 'YANDEX';
type MarketInfo = { available: boolean; total: number | null; report_count?: number; incomplete_reports?: number; message?: string };
type PayoutData = { marketplaces: Record<Marketplace, MarketInfo>; note: string };
type WeeklyPeriod = { date_from: string; date_to: string; estimated_issued_at: string; estimated_available_at: string; date_reached: boolean; complete: boolean; report_count: number; complete_count: number; amount: number | null; report_ids: number[] };
type WeeklyData = { items: WeeklyPeriod[]; note: string };
type OzonWeeklyPeriod = {date_from: string; date_to: string; amount: number | null; loaded_days: number; expected_days: number; complete: boolean; estimated_payment_at: string; date_reached: boolean; calendar_adjustment_applied: boolean; status: string};
type OzonWeeklyData = {items: OzonWeeklyPeriod[]; note: string};
const formatDate = (value: string) => value.split('-').reverse().join('.');
const MARKETPLACES: Marketplace[] = ['WB', 'OZON', 'YANDEX'];
const LABELS: Record<Marketplace, string> = { WB: 'WB', OZON: 'Ozon', YANDEX: 'Я.Маркет' };
const API = `${window.location.protocol}//${window.location.hostname}:8000`;
const money = (value: number) => `${value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽`;
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
function initialPeriod() {
  const today = new Date();
  return { from: iso(new Date(today.getFullYear(), today.getMonth(), 1)), to: iso(today) };
}

export default function PayoutsDashboard() {
  const initial = useMemo(initialPeriod, []);
  const [from, setFrom] = useState(initial.from);
  const [to, setTo] = useState(initial.to);
  const [selected, setSelected] = useState<Marketplace[]>(MARKETPLACES);
  const [data, setData] = useState<PayoutData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<Marketplace | null>(null);
  const [weekly, setWeekly] = useState<WeeklyData | null>(null);
  const [weeklyLoading, setWeeklyLoading] = useState(false);
  const [weeklyError, setWeeklyError] = useState('');
  const [ozonWeekly, setOzonWeekly] = useState<OzonWeeklyData | null>(null);
  const isAll = selected.length === MARKETPLACES.length;
  const activePayouts = selected.map(m => data?.marketplaces[m]).filter((m): m is MarketInfo => Boolean(m?.available && m.total !== null));
  const payoutTotal = activePayouts.reduce((sum, m) => sum + (m.total ?? 0), 0);
  const payoutPartial = selected.some(m => !data?.marketplaces[m]?.available || data?.marketplaces[m]?.total === null);
  const payoutUnverified = selected.some(m => (data?.marketplaces[m]?.incomplete_reports ?? 0) > 0);
  const valid = Boolean(from && to && from <= to && (new Date(to).getTime() - new Date(from).getTime()) <= 366 * 86400000);

  useEffect(() => {
    if (!valid) { setData(null); return; }
    const controller = new AbortController();
    setLoading(true);
    fetch(`${API}/analytics/payouts-dashboard?date_from=${from}&date_to=${to}`, { credentials: 'include', signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
      .then((result: PayoutData) => { if (!controller.signal.aborted) { setData(result); setError(''); } })
      .catch(e => { if (!controller.signal.aborted) { setError(e instanceof Error ? e.message : String(e)); setData(null); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [from, to, valid]);

  useEffect(() => {
    if (!valid || expanded !== 'WB') { setWeekly(null); return; }
    const controller = new AbortController();
    setWeeklyLoading(true);
    fetch(`${API}/analytics/payouts-dashboard/weekly-periods?date_from=${from}&date_to=${to}`, { credentials: 'include', signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
      .then((result: WeeklyData) => { if (!controller.signal.aborted) { setWeekly(result); setWeeklyError(''); } })
      .catch(error => { if (!controller.signal.aborted) { setWeeklyError(String(error)); setWeekly(null); } })
      .finally(() => { if (!controller.signal.aborted) setWeeklyLoading(false); });
    return () => controller.abort();
  }, [expanded, from, to, valid]);

  useEffect(() => {
    if (!valid || expanded !== 'OZON') { setOzonWeekly(null); return; }
    const controller = new AbortController();
    setWeeklyLoading(true);
    fetch(`${API}/analytics/payouts-dashboard/ozon-weekly-periods?date_from=${from}&date_to=${to}`, {credentials:'include',signal:controller.signal})
      .then(async r => {if(!r.ok) throw new Error(`HTTP ${r.status}`);return r.json();})
      .then((result: OzonWeeklyData) => {if(!controller.signal.aborted){setOzonWeekly(result);setWeeklyError('');}})
      .catch(e => {if(!controller.signal.aborted){setOzonWeekly(null);setWeeklyError(String(e));}})
      .finally(() => {if(!controller.signal.aborted)setWeeklyLoading(false);});
    return () => controller.abort();
  }, [expanded,from,to,valid]);

  const select = (marketplace: Marketplace) => setSelected(previous =>
    previous.length === MARKETPLACES.length
      ? [marketplace]
      : previous.includes(marketplace)
        ? previous.length === 1 ? previous : previous.filter(m => m !== marketplace)
        : MARKETPLACES.filter(m => previous.includes(m) || m === marketplace)
  );

  return <section className="payout-dash">
    <div className="payout-head"><h2>К выплате за период</h2><span>По датам финансовых отчётов</span></div>
    <div className="payout-filters">
      <DashboardPeriodPicker from={from} to={to} onChange={(nextFrom,nextTo)=>{setFrom(nextFrom);setTo(nextTo)}} label="Период финансовых отчётов" />
      <div className="payout-picks">
        <button type="button" className={isAll ? 'active' : ''} onClick={() => setSelected(MARKETPLACES)}>Все</button>
        {MARKETPLACES.map(m => <button type="button" key={m} className={!isAll && selected.includes(m) ? 'active' : ''} onClick={() => select(m)}>{LABELS[m]}</button>)}
      </div>
    </div>
    {!valid && <p className="payout-error">Укажите период не более 367 дней, с датой начала не позже окончания.</p>}
    {error && <p role="alert" className="payout-error">Не удалось загрузить данные: {error}</p>}
    {loading && <p className="payout-note">Обновление сумм…</p>}
    <div className="payout-cards payout-cards-with-total">
      <div className="payout-card payout-card-total" aria-label="Сумма к выплате по выбранным маркетплейсам">
        <span>Все · сумма выбранных</span>
        <strong>{!data ? '—' : activePayouts.length ? money(payoutTotal) : 'Нет данных'}</strong>
        <small>{payoutPartial ? 'Частичная сумма: не все МП подключены' : payoutUnverified ? 'Предварительно: есть несверенные отчёты' : 'Все выбранные МП'}</small>
      </div>
      {MARKETPLACES.filter(m => selected.includes(m)).map(m => {
        const item = data?.marketplaces[m];
        return <button type="button" className={`payout-card payout-card-button${expanded === m ? ' selected' : ''}`} key={m} onClick={() => setExpanded(current => current === m ? null : m)} aria-expanded={expanded === m}>
          <span>{LABELS[m]}</span>
          <strong>{!item ? '—' : item.available ? money(item.total ?? 0) : 'Нет данных'}</strong>
          <small>{item?.available ? `Финансовых отчётов: ${item.report_count ?? 0}` : item?.message ?? 'Нет подтверждённого источника'}</small>
        </button>;
      })}
    </div>
    {expanded && selected.includes(expanded) && <div className="payout-breakdown">
      <h3>Детализация — {LABELS[expanded]}</h3>
      {expanded === 'OZON' ? <>
        <p className="payout-note">Общая карточка Ozon выше суммирует ежедневные начисления строго за выбранные даты. Ниже — отдельная группировка по полным календарным неделям, пересекающим выбранный диапазон. Суммы могут отличаться на границах периода.</p>
        {weeklyLoading && <p className="payout-note">Загрузка периодов…</p>}
        {weeklyError && <p role="alert" className="payout-error">{weeklyError}</p>}
        {ozonWeekly && <div className="payout-table-wrap"><table className="payout-period-table"><thead><tr><th>Период отчёта</th><th>К выплате (начислено)</th><th>Расчётная дата выплаты*</th><th>Состояние</th></tr></thead><tbody>
          {ozonWeekly.items.map(item => <tr key={item.date_from}>
            <td>{formatDate(item.date_from)} — {formatDate(item.date_to)}</td>
            <td>{item.amount === null ? '—' : money(item.amount)}{!item.complete && <small className="payout-incomplete">Неполная сумма</small>}</td>
            <td>{formatDate(item.estimated_payment_at)}</td>
            <td>{!item.complete ? `Загружено ${item.loaded_days} из ${item.expected_days} доступных дней` : item.date_reached ? 'Расчётная дата наступила' : 'Ожидается'}</td>
          </tr>)}
          {ozonWeekly.items.length === 0 && <tr><td colSpan={4}>За выбранный период отчёты не найдены.</td></tr>}
        </tbody></table></div>}
        <p className="payout-note">* {ozonWeekly?.note ?? 'Даты расчётные, не подтверждены Ozon API.'}</p>
      </> : expanded !== 'WB' ? <p className="payout-note">Финансовая детализация {LABELS[expanded]} пока не подключена.</p> : <>
        <p className="payout-note">Ниже — выплаты по еженедельным отчётам WB. Основной отчёт и выкупы одного периода объединены. Это отдельная сводка: общий показатель выше рассчитывается по ежедневным отчётам.</p>
        {weeklyLoading && <p className="payout-note">Загружаем периоды…</p>}
        {weeklyError && <p role="alert" className="payout-error">{weeklyError}</p>}
        {weekly && <div className="payout-table-wrap"><table className="payout-period-table"><thead><tr><th>Период отчёта</th><th>К выплате</th><th>Дата формирования*</th><th>Доступно к выводу с*</th><th>Состояние</th></tr></thead><tbody>
          {weekly.items.map(item => <tr key={`${item.date_from}_${item.date_to}`}>
            <td>{formatDate(item.date_from)} — {formatDate(item.date_to)}</td>
            <td>{item.amount === null ? '—' : money(item.amount)}{!item.complete ? <small className="payout-incomplete">Неполная сумма</small> : null}</td>
            <td>{formatDate(item.estimated_issued_at)}</td>
            <td>{formatDate(item.estimated_available_at)}</td>
            <td>{!item.complete ? `Загрузка (${item.complete_count}/${item.report_count})` : item.date_reached ? 'Расчётная дата наступила' : 'Ожидается'}</td>
          </tr>)}
          {weekly.items.length === 0 && <tr><td colSpan={5}>За выбранный период недельные отчёты не найдены.</td></tr>}
        </tbody></table></div>}
        <p className="payout-note">* Даты ориентировочные: предполагаем формирование в ближайший понедельник после отчётного периода и возможность вывода через 14 дней. Это не подтверждение доступного баланса или факта вывода. {weekly?.note || ''}</p>
      </>}
    </div>}
    {selected.includes('WB') && (data?.marketplaces.WB.incomplete_reports ?? 0) > 0 &&
      <p className="payout-note">WB: {data?.marketplaces.WB.incomplete_reports} отчётов ещё не сверены. Сумма предварительная и может измениться.</p>}
    <p className="payout-note">{data?.note ?? 'Данные за период будут загружены из финансовых отчётов.'}</p>
  </section>;
}
