import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import DateFilter from './DateFilter';
import './Analytics.css';
import './WeeklyReport.css';

type WeeklyReportItem = {
  report_id: number;
  date_from: string;
  date_to: string;
  report_type: number | string;
  status: string;
  loaded_rows: number;
  last_error: string | null;
  expected_retail: string;
  expected_for_pay: string;
  expected_bank_payment: string;
  expected_logistics: string;
  expected_storage: string;
  expected_acceptance: string;
  expected_penalty: string;
  expected_deduction: string;
  expected_additional_payment: string;
  retail: string;
  for_pay: string;
  commission: string;
  vat: string;
  acquiring: string;
  logistics: string;
  storage: string;
  acceptance: string;
  penalty: string;
  deduction: string;
  additional_payment: string;
};

type DailyReportItem = {
  report_id: number;
  report_date: string;
  report_type: number | string;
  status: string;
  loaded_rows: number;
  last_error: string | null;
  updated_at: string;
  expected_retail: string;
  expected_for_pay: string;
  expected_bank_payment: string;
  expected_logistics: string;
  expected_penalty: string;
  expected_deduction: string;
  retail: string;
  for_pay: string;
  commission: string;
  vat: string;
  acquiring: string;
  logistics: string;
  storage: string;
  acceptance: string;
  penalty: string;
  deduction: string;
  additional_payment: string;
};

type DailyMetricDetail = {
  identifier: string;
  reason: string;
  operation: string;
  attribution: 'general' | 'sku_candidate';
  rows: number;
  amount: string;
};

type ViewMode = 'daily' | 'weekly';
type Marketplace = 'WB' | 'OZON' | 'YANDEX';
type DailyMetricKey =
  | 'retail'
  | 'commission'
  | 'vat'
  | 'acquiring'
  | 'for_pay'
  | 'logistics'
  | 'storage'
  | 'acceptance'
  | 'penalty'
  | 'deduction'
  | 'additional_payment'
  | 'bank_payment';

const api = `${window.location.protocol}//${window.location.hostname}:8000`;
const statusLabel: Record<string, string> = {
  queued: 'В очереди',
  loading: 'Загружается',
  retry: 'Повтор запроса',
  complete: 'Сверено',
  mismatch: 'Расхождение',
};
const reportTypeLabel: Record<string, string> = { '1': 'Основной', '2': 'По выкупам' };
const metricLabels: Record<DailyMetricKey, string> = {
  retail: 'Реализация',
  commission: 'Комиссия WB без НДС',
  vat: 'НДС на комиссию',
  acquiring: 'Эквайринг',
  for_pay: 'К перечислению за товар',
  logistics: 'Логистика',
  storage: 'Хранение',
  acceptance: 'Платная приёмка',
  penalty: 'Штрафы',
  deduction: 'Удержания',
  additional_payment: 'Доплаты',
  bank_payment: 'Итого к оплате (сводка WB)',
};

function toNumber(value: string | number | null | undefined): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0;
  if (typeof value !== 'string') return 0;
  const parsed = Number(value.replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : 0;
}

function rub(value: string | number | null | undefined): string {
  return `${toNumber(value).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽`;
}

function iso(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? `${match[3]}.${match[2]}.${match[1]}` : value;
}

function defaultRange(): { from: string; to: string } {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 6);
  return { from: iso(start), to: iso(end) };
}

function typeLabel(value: number | string): string {
  return reportTypeLabel[String(value)] || `Тип ${value}`;
}

function resolveValue(primary: string | number | null | undefined, fallback: string | number | null | undefined): number {
  const first = toNumber(primary);
  if (Math.abs(first) > 0.000001) return first;
  return toNumber(fallback);
}

function dailyBankPayment(row: DailyReportItem | null): number {
  if (!row) return 0;
  const expected = toNumber(row.expected_bank_payment);
  if (Math.abs(expected) > 0.000001) return expected;
  return toNumber(row.for_pay) - toNumber(row.logistics) - toNumber(row.storage) - toNumber(row.acceptance) - toNumber(row.penalty) - toNumber(row.deduction) + toNumber(row.additional_payment);
}

export default function WeeklyReport() {
  const initial = useMemo(() => defaultRange(), []);
  const [view, setView] = useState<ViewMode>('daily');
  const [marketplace, setMarketplace] = useState<Marketplace>('WB');
  const [dateFrom, setDateFrom] = useState(initial.from);
  const [dateTo, setDateTo] = useState(initial.to);

  const [dailyReports, setDailyReports] = useState<DailyReportItem[]>([]);
  const [dailyError, setDailyError] = useState('');
  const [dailyBusy, setDailyBusy] = useState(false);
  const [selectedDaily, setSelectedDaily] = useState<number | null>(null);
  const [activeMetric, setActiveMetric] = useState<DailyMetricKey | null>(null);
  const [metricDetails, setMetricDetails] = useState<DailyMetricDetail[]>([]);
  const [metricBusy, setMetricBusy] = useState(false);
  const [metricError, setMetricError] = useState('');

  const [weeklyReports, setWeeklyReports] = useState<WeeklyReportItem[]>([]);
  const [weeklySelected, setWeeklySelected] = useState<number | null>(null);
  const [weeklyFrom, setWeeklyFrom] = useState('2025-01-01');
  const [weeklyTo, setWeeklyTo] = useState(initial.to);
  const [weeklyMetric, setWeeklyMetric] = useState<DailyMetricKey | null>(null);
  const [weeklyDetails, setWeeklyDetails] = useState<DailyMetricDetail[]>([]);
  const [weeklyMetricBusy, setWeeklyMetricBusy] = useState(false);
  const [weeklyMetricError, setWeeklyMetricError] = useState('');
  const [weeklyError, setWeeklyError] = useState('');

  const [showScrollTop, setShowScrollTop] = useState(false);
  const dailyDetailRef = useRef<HTMLDivElement | null>(null);
  const weeklyDetailRef = useRef<HTMLDivElement | null>(null);

  const loadWeekly = useCallback(async () => {
    try {
      const response = await fetch(`${api}/analytics/wb-finance/reports?date_from=${weeklyFrom}&date_to=${weeklyTo}`, { credentials: 'include' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const items = (data.items || []) as WeeklyReportItem[];
      setWeeklyReports(items);
      setWeeklySelected((current) => (current && items.some((item) => item.report_id === current) ? current : current ?? null));
      setWeeklyError('');
    } catch (error) {
      setWeeklyError(error instanceof Error ? error.message : String(error));
    }
  }, [weeklyFrom, weeklyTo]);

  const loadDaily = useCallback(async () => {
    if (!dateFrom || !dateTo) return;
    setDailyBusy(true);
    try {
      const response = await fetch(`${api}/analytics/wb-finance/daily?date_from=${dateFrom}&date_to=${dateTo}`, { credentials: 'include' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const items = (data.items || []) as DailyReportItem[];
      setDailyReports(items);
      setSelectedDaily((current) => {
        if (current && items.some((item) => item.report_id === current)) return current;
        return items[0]?.report_id ?? null;
      });
      setDailyError('');
    } catch (error) {
      setDailyError(error instanceof Error ? error.message : String(error));
    } finally {
      setDailyBusy(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => {
    void loadWeekly();
    const timer = setInterval(() => void loadWeekly(), 60000);
    return () => clearInterval(timer);
  }, [loadWeekly]);

  useEffect(() => {
    void loadDaily();
    const timer = setInterval(() => void loadDaily(), 60000);
    return () => clearInterval(timer);
  }, [loadDaily]);

  useEffect(() => {
    if (weeklySelected === null || weeklyMetric === null) {
      setWeeklyDetails([]);
      setWeeklyMetricError('');
      return;
    }
    let alive = true;
    setWeeklyMetricBusy(true);
    fetch(`${api}/analytics/wb-finance/reports/${weeklySelected}/metric-details?metric=${weeklyMetric}&limit=500`, { credentials: 'include' })
      .then(async response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
      .then(data => { if (alive) { setWeeklyDetails(data.items || []); setWeeklyMetricError(''); } })
      .catch(error => { if (alive) { setWeeklyMetricError(String(error)); setWeeklyDetails([]); } })
      .finally(() => { if (alive) setWeeklyMetricBusy(false); });
    return () => { alive = false; };
  }, [weeklySelected, weeklyMetric]);

  const visibleWeekly = useMemo(() => weeklyReports.filter(r =>
    (!weeklyFrom || r.date_to >= weeklyFrom) && (!weeklyTo || r.date_from <= weeklyTo)
  ), [weeklyReports, weeklyFrom, weeklyTo]);

  const handleWeeklySelect = (id: number) => {
    setWeeklySelected(id);
    setWeeklyMetric(null);
    requestAnimationFrame(() => weeklyDetailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  useEffect(() => {
    if (selectedDaily === null || activeMetric === null) {
      setMetricDetails([]);
      setMetricError('');
      return;
    }
    let alive = true;
    setMetricBusy(true);
    fetch(`${api}/analytics/wb-finance/daily/${selectedDaily}/metric-details?metric=${activeMetric}&limit=500`, { credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (!alive) return;
        setMetricDetails(data.items || []);
        setMetricError('');
      })
      .catch((error) => {
        if (alive) {
          setMetricDetails([]);
          setMetricError(error instanceof Error ? error.message : String(error));
        }
      })
      .finally(() => {
        if (alive) setMetricBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [activeMetric, selectedDaily]);

  useEffect(() => {
    const onScroll = () => setShowScrollTop(window.scrollY > 220);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const selectedDailyReport = useMemo(
    () => dailyReports.find((item) => item.report_id === selectedDaily) ?? null,
    [dailyReports, selectedDaily],
  );
  const selectedWeeklyReport = useMemo(
    () => weeklyReports.find((item) => item.report_id === weeklySelected) ?? null,
    [weeklyReports, weeklySelected],
  );

  const summaryCards = useMemo(() => {
    const row = selectedDailyReport;
    if (!row) return [] as Array<{ key: DailyMetricKey; label: string; value: number }>;
    return [
      { key: 'retail' as DailyMetricKey, label: metricLabels.retail, value: resolveValue(row.retail, row.expected_retail) },
      { key: 'commission' as DailyMetricKey, label: metricLabels.commission, value: toNumber(row.commission) },
      { key: 'vat' as DailyMetricKey, label: metricLabels.vat, value: toNumber(row.vat) },
      { key: 'acquiring' as DailyMetricKey, label: metricLabels.acquiring, value: toNumber(row.acquiring) },
      { key: 'for_pay' as DailyMetricKey, label: metricLabels.for_pay, value: resolveValue(row.for_pay, row.expected_for_pay) },
      { key: 'logistics' as DailyMetricKey, label: metricLabels.logistics, value: resolveValue(row.logistics, row.expected_logistics) },
      { key: 'storage' as DailyMetricKey, label: metricLabels.storage, value: toNumber(row.storage) },
      { key: 'acceptance' as DailyMetricKey, label: metricLabels.acceptance, value: toNumber(row.acceptance) },
      { key: 'penalty' as DailyMetricKey, label: metricLabels.penalty, value: resolveValue(row.penalty, row.expected_penalty) },
      { key: 'deduction' as DailyMetricKey, label: metricLabels.deduction, value: resolveValue(row.deduction, row.expected_deduction) },
      { key: 'additional_payment' as DailyMetricKey, label: metricLabels.additional_payment, value: toNumber(row.additional_payment) },
      { key: 'bank_payment' as DailyMetricKey, label: metricLabels.bank_payment, value: dailyBankPayment(row) },
    ];
  }, [selectedDailyReport]);

  const handleDailySelect = useCallback((reportId: number) => {
    setSelectedDaily(reportId);
    requestAnimationFrame(() => {
      dailyDetailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, []);

  return (
    <div className="analytics-page weekly-report-page">
      <div className="analytics-header">
        <div>
          <h1>Финансовые отчёты</h1>
          <p>Ежедневные и еженедельные финансовые отчёты маркетплейсов.</p>
        </div>
      </div>

      <div className="wb-finance-controls">
        <div className="wb-finance-marketplaces" role="group" aria-label="Маркетплейс">
          {([['WB', 'WB'], ['OZON', 'Ozon'], ['YANDEX', 'Я.Маркет']] as const).map(([key, label]) => (
            <button key={key} type="button" className={`wb-finance-tab${marketplace === key ? ' active' : ''}`} onClick={() => setMarketplace(key)} aria-pressed={marketplace === key}>{label}</button>
          ))}
        </div>
      <div className="wb-finance-tabs" role="group" aria-label="Период отчётов">
        <button type="button" className={`wb-finance-tab${view === 'daily' ? ' active' : ''}`} onClick={() => setView('daily')}>Ежедневные</button>
        <button type="button" className={`wb-finance-tab${view === 'weekly' ? ' active' : ''}`} onClick={() => setView('weekly')}>Еженедельные</button>
      </div>
      </div>

      {marketplace !== 'WB' ? (
        <section className="wb-finance-section wb-finance-upcoming" role="status">
          <h2>{marketplace === 'OZON' ? 'Ozon' : 'Я.Маркет'}</h2>
          <p>Финансовые отчёты для этой площадки пока не подключены. Выбранный режим: {view === 'daily' ? 'Ежедневные' : 'Еженедельные'}. Данные WB не подменяются данными другого маркетплейса.</p>
        </section>
      ) : view === 'daily' ? (
        <section className="wb-finance-section">
          <header className="wb-finance-section-header wb-finance-section-header--stacked">
            <div>
              <h2>Ежедневные отчёты WB</h2>
            </div>
            <div className="wb-finance-section-note">Даты финансовых отчётов, не даты заказов</div>
          </header>

          <div className="wb-finance-filters">
            <label className="wb-finance-filter">
              <span>С</span>
              <DateFilter value={dateFrom} onChange={setDateFrom} ariaLabel="Дата начала периода ежедневных отчётов" />
            </label>
            <label className="wb-finance-filter">
              <span>По</span>
              <DateFilter value={dateTo} onChange={setDateTo} ariaLabel="Дата окончания периода ежедневных отчётов" />
            </label>
            <button type="button" className="wb-finance-refresh" onClick={() => void loadDaily()} disabled={dailyBusy}>
              {dailyBusy ? 'Обновление…' : 'Обновить'}
            </button>
          </div>

          {dailyError && <p role="alert" className="weekly-error">{dailyError}</p>}

          <div className="weekly-table-wrap">
            <table className="wb-finance-table">
              <thead>
                <tr>
                  <th>Дата отчёта</th>
                  <th>Тип</th>
                  <th>К перечислению за товар</th>
                  <th>Логистика</th>
                  <th>Штрафы</th>
                  <th>Удержания</th>
                  <th>Итого к оплате</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {dailyReports.map((report) => {
                  const bankPayment = dailyBankPayment(report);
                  return (
                    <tr
                      key={report.report_id}
                      className={selectedDaily === report.report_id ? 'selected' : ''}
                      onClick={() => handleDailySelect(report.report_id)}
                    >
                      <td>{formatDate(report.report_date)}</td>
                      <td>{typeLabel(report.report_type)}</td>
                      <td>{rub(resolveValue(report.for_pay, report.expected_for_pay))}</td>
                      <td>{rub(resolveValue(report.logistics, report.expected_logistics))}</td>
                      <td>{rub(resolveValue(report.penalty, report.expected_penalty))}</td>
                      <td>{rub(resolveValue(report.deduction, report.expected_deduction))}</td>
                      <td>{rub(bankPayment)}</td>
                      <td>{statusLabel[report.status] || report.status}</td>
                    </tr>
                  );
                })}
                {!dailyReports.length && !dailyBusy && (
                  <tr>
                    <td colSpan={8} className="wb-finance-empty">За выбранный период отчёты пока не найдены.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {selectedDailyReport && (
            <div ref={dailyDetailRef} className="wb-finance-daily-detail">
              <h3>
                Отчёт №{selectedDailyReport.report_id} · {typeLabel(selectedDailyReport.report_type)}
              </h3>
              <p className="wb-finance-detail-meta">
                Дата отчёта: {formatDate(selectedDailyReport.report_date)} · Строк: {selectedDailyReport.loaded_rows.toLocaleString('ru-RU')} · {statusLabel[selectedDailyReport.status] || selectedDailyReport.status}
                {selectedDailyReport.last_error ? ` · ${selectedDailyReport.last_error}` : ''}
              </p>

              <div className="wb-finance-metrics-grid">
                {summaryCards.map((card) => (
                  <button
                    key={card.key}
                    type="button"
                    className={`wb-finance-metric-card${activeMetric === card.key ? ' active' : ''}`}
                    onClick={() => setActiveMetric(card.key)}
                  >
                    <span className="wb-finance-metric-label">{card.label}</span>
                    <strong className="wb-finance-metric-value">{rub(card.value)}</strong>
                  </button>
                ))}
                <div className="wb-finance-metric-card wb-finance-margin-placeholder" title="Расчёт чистой прибыли будет добавлен позднее">
                  <span className="wb-finance-metric-label">Маржа</span>
                  <strong className="wb-finance-metric-value">—</strong>
                  <span className="wb-finance-margin-caption">Расчёт в разработке</span>
                </div>
              </div>

              <div className="wb-finance-breakdown">
                <div className="wb-finance-breakdown-header">
                  <div>
                    <h4>Обоснование оплаты</h4>
                    <p>
                      {activeMetric ? `Показатель: ${metricLabels[activeMetric]}` : 'Нажмите на любой показатель выше, чтобы увидеть детализацию по основаниям, операциям и SKU.'}
                    </p>
                  </div>
                </div>

                {metricError && <p role="alert" className="weekly-error">{metricError}</p>}

                {!activeMetric ? (
                  <div className="wb-finance-breakdown-empty">Выберите показатель в карточках выше.</div>
                ) : metricBusy ? (
                  <div className="wb-finance-breakdown-empty">Загрузка детализации…</div>
                ) : (
                  <div className="weekly-table-wrap">
                    <table className="wb-finance-table wb-finance-table--detail">
                      <caption className="wb-finance-count-note">Кол-во — число записей финансового отчёта, не число уникальных артикулов.</caption>
                      <thead>
                        <tr>
                          <th>Основание</th>
                          <th>Операция</th>
                          <th>SKU / артикул</th>
                          <th>Кол-во</th>
                          <th>Сумма</th>
                        </tr>
                      </thead>
                      <tbody>
                        {metricDetails.map((item, index) => (
                          <tr key={`${item.reason}-${item.operation}-${item.identifier || 'general'}-${index}`}>
                            <td>{item.reason || 'Не указано'}</td>
                            <td>{item.operation || '—'}</td>
                            <td>{item.identifier || ''}</td>
                            <td>{item.rows.toLocaleString('ru-RU')}</td>
                            <td>{rub(item.amount)}</td>
                          </tr>
                        ))}
                        {!metricDetails.length && (
                          <tr>
                            <td colSpan={5} className="wb-finance-empty">Для выбранного показателя нет строк с ненулевой суммой.</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
      ) : (
        <section className="wb-finance-section">
          <header className="wb-finance-section-header wb-finance-section-header--stacked">
            <h2>Еженедельные отчёты WB</h2>
            <div className="wb-finance-section-note">Период финансового отчёта WB, не даты заказов</div>
          </header>
          <div className="wb-finance-filters">
            <label className="wb-finance-filter"><span>С</span><DateFilter value={weeklyFrom} onChange={setWeeklyFrom} ariaLabel="Недели с даты" /></label>
            <label className="wb-finance-filter"><span>По</span><DateFilter value={weeklyTo} onChange={setWeeklyTo} ariaLabel="Недели по дату" /></label>
            <button type="button" className="wb-finance-refresh" onClick={() => void loadWeekly()}>Обновить</button>
          </div>
          {weeklyError && <p role="alert" className="weekly-error">{weeklyError}</p>}
          <div className="weekly-table-wrap">
            <table className="wb-finance-table">
              <thead><tr><th>Период отчёта</th><th>№ отчёта</th><th>Тип</th>
                <th>К перечислению за товар</th><th>Логистика</th><th>Штрафы</th>
                <th>Удержания</th><th>Итого к оплате</th><th>Статус</th></tr></thead>
              <tbody>
                {visibleWeekly.map(report => <tr key={report.report_id}
                  className={weeklySelected === report.report_id ? 'selected' : ''}
                  onClick={() => handleWeeklySelect(report.report_id)}>
                  <td>{formatDate(report.date_from)} — {formatDate(report.date_to)}</td>
                  <td>{report.report_id}</td>
                  <td>{typeLabel(report.report_type)}</td>
                  <td>{rub(report.expected_for_pay)}</td>
                  <td>{rub(report.expected_logistics)}</td>
                  <td>{rub(report.expected_penalty)}</td>
                  <td>{rub(report.expected_deduction)}</td>
                  <td>{rub(report.expected_bank_payment)}</td>
                  <td>{statusLabel[report.status] || report.status}</td>
                </tr>)}
                {!visibleWeekly.length && <tr><td colSpan={9} className="wb-finance-empty">Нет еженедельных отчётов за выбранный период. Новые отчёты появятся после фоновой загрузки WB.</td></tr>}
              </tbody>
            </table>
          </div>
          {selectedWeeklyReport && visibleWeekly.some(r => r.report_id === selectedWeeklyReport.report_id) &&
            <div className="weekly-detail" ref={weeklyDetailRef}>
              <h3>Отчёт №{selectedWeeklyReport.report_id} · {formatDate(selectedWeeklyReport.date_from)} — {formatDate(selectedWeeklyReport.date_to)}</h3>
              <p className="wb-finance-detail-meta">Тип: {typeLabel(selectedWeeklyReport.report_type)} · Строк: {selectedWeeklyReport.loaded_rows.toLocaleString('ru-RU')} · {statusLabel[selectedWeeklyReport.status] || selectedWeeklyReport.status}</p>
              {selectedWeeklyReport.status !== 'complete' && <p className="weekly-error">{selectedWeeklyReport.last_error || 'Детализация ещё загружается или сверка не завершена.'}</p>}
              <div className="wb-finance-metrics-grid">
                {([
                  {key:'retail', label:'Реализация', amount:selectedWeeklyReport.expected_retail},
                  {key:'commission', label:'Комиссия WB без НДС', amount:selectedWeeklyReport.commission},
                  {key:'vat', label:'НДС на комиссию', amount:selectedWeeklyReport.vat},
                  {key:'acquiring', label:'Эквайринг', amount:selectedWeeklyReport.acquiring},
                  {key:'for_pay', label:'К перечислению за товар', amount:selectedWeeklyReport.expected_for_pay},
                  {key:'logistics', label:'Логистика', amount:selectedWeeklyReport.expected_logistics},
                  {key:'storage', label:'Хранение', amount:selectedWeeklyReport.expected_storage},
                  {key:'acceptance', label:'Платная приёмка', amount:selectedWeeklyReport.expected_acceptance},
                  {key:'penalty', label:'Штрафы', amount:selectedWeeklyReport.expected_penalty},
                  {key:'deduction', label:'Удержания', amount:selectedWeeklyReport.expected_deduction},
                  {key:'additional_payment', label:'Доплаты', amount:selectedWeeklyReport.expected_additional_payment},
                  {key:'bank_payment', label:'Итого к оплате (сводка WB)', amount:selectedWeeklyReport.expected_bank_payment},
                ] as Array<{key: DailyMetricKey; label: string; amount: string}>).map(card =>
                  <button key={card.key} type="button"
                    className={`wb-finance-metric-card${weeklyMetric === card.key ? ' active' : ''}`}
                    onClick={() => setWeeklyMetric(card.key)}>
                    <span className="wb-finance-metric-label">{card.label}</span>
                    <strong className="wb-finance-metric-value">{card.key === 'commission' || card.key === 'vat' || card.key === 'acquiring' ? (selectedWeeklyReport.status === 'complete' ? rub(card.amount) : '—') : rub(card.amount)}</strong>
                  </button>)}
                <div className="wb-finance-metric-card wb-finance-margin-placeholder">
                  <span className="wb-finance-metric-label">Маржа</span>
                  <strong className="wb-finance-metric-value">—</strong>
                  <span className="wb-finance-margin-caption">Расчёт в разработке</span>
                </div>
              </div>
              <div className="wb-finance-breakdown">
                <div className="wb-finance-breakdown-header"><div>
                  <h4>Обоснование оплаты</h4>
                  <p>{weeklyMetric ? metricLabels[weeklyMetric] : 'Выберите показатель для просмотра операций и SKU.'}</p>
                </div></div>
                {weeklyMetricError && <p role="alert" className="weekly-error">{weeklyMetricError}</p>}
                {!weeklyMetric ? <div className="wb-finance-breakdown-empty">Нажмите на карточку показателя.</div>
                  : weeklyMetricBusy ? <div className="wb-finance-breakdown-empty">Загрузка детализации…</div>
                  : <div className="weekly-table-wrap"><table className="wb-finance-table wb-finance-table--detail">
                      <caption className="wb-finance-count-note">Кол-во — количество записей отчёта, а не уникальных артикулов.</caption>
                      <thead><tr><th>Основание</th><th>Операция</th><th>SKU / артикул</th><th>Кол-во</th><th>Сумма</th></tr></thead>
                      <tbody>{weeklyDetails.map((r,i) => <tr key={`${r.identifier}-${r.reason}-${i}`}>
                        <td>{r.reason || 'Не указано'}</td><td>{r.operation || '—'}</td>
                        <td>{r.identifier || ''}</td><td>{r.rows.toLocaleString('ru-RU')}</td><td>{rub(r.amount)}</td>
                      </tr>)}
                      {!weeklyDetails.length && <tr><td colSpan={5} className="wb-finance-empty">Операции по этому показателю не найдены.</td></tr>}
                      </tbody></table></div>}
              </div>
            </div>}
        </section>
      )}

      {showScrollTop && (
        <button
          type="button"
          className="reviews-scroll-top"
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          aria-label="Наверх"
          title="Наверх"
        >
          ↑
        </button>
      )}
    </div>
  );
}
