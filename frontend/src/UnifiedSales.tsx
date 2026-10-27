import { useEffect, useMemo, useState } from "react";
import "./UnifiedSales.css";

type Market = "wb" | "ozon" | "yandex";
type Row = { date: string; revenue: number; ordered_units: number; cancel_count?: number; cancel_sum?: number; loaded?: boolean };
type Series = { rows: Row[]; coverage?: { complete: boolean; loaded_days: number; period_days: number } };
type Estimate = { rows: { date: string; estimated_rub: number }[]; note?: string };
const MARKETS: { id: Market; title: string }[] = [
  { id: "wb", title: "Wildberries" }, { id: "ozon", title: "Ozon" }, { id: "yandex", title: "Яндекс Маркет" },
];
const dateString = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const current = new Date();
const first = new Date(current.getFullYear(), current.getMonth(), current.getDate() - 29);
const money = (value: number) => `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
const shortDate = (s: string) => new Date(`${s}T12:00:00`).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });

function dateAdd(d: Date, days: number) { const n = new Date(d); n.setDate(n.getDate() + days); return n; }
function monthDays(y: number, m: number) { return new Date(y, m + 1, 0).getDate(); }

export default function UnifiedSales() {
  const [from, setFrom] = useState(dateString(first));
  const [to, setTo] = useState(dateString(current));
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarCursor, setCalendarCursor] = useState(() => new Date(current.getFullYear(), current.getMonth(), 1));
  const [draftStart, setDraftStart] = useState<string | null>(null);
  const [priceMode, setPriceMode] = useState<"seller" | "realization">("seller");
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [group, setGroup] = useState<"day" | "month">("day");
  const [enabled, setEnabled] = useState<Market[]>(["wb", "ozon", "yandex"]);
  const [allSelected, setAllSelected] = useState(true);
  const [showPrevious, setShowPrevious] = useState(true);
  const [available, setAvailable] = useState<Market[]>([]);
  const [viewSettingsError, setViewSettingsError] = useState<string | null>(null);
  const [viewReady, setViewReady] = useState(false);
  const [metricTip, setMetricTip] = useState<"cancels" | "returns" | null>(null);
  const [data, setData] = useState<Partial<Record<Market, Series>>>({});
  const [errors, setErrors] = useState<Partial<Record<Market, string>>>({});
  const [priorData, setPriorData] = useState<Partial<Record<Market, Series>>>({});
  const [priorEstimate, setPriorEstimate] = useState<Estimate | null>(null);
  const [loading, setLoading] = useState(false);
  const [tooltip, setTooltip] = useState<{ key: string; x: number; y: number } | null>(null);
  useEffect(() => {
    let active = true;
    const loadSettings = async () => {
      try {
        const response = await fetch(`${window.location.protocol}//${window.location.hostname}:8000/settings/stock-view`, { credentials: "include" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const settings = await response.json();
        if (!active) return;
        const allowed = MARKETS.filter(m => settings[m.id] === true).map(m => m.id);
        setAvailable(allowed);
        setEnabled(old => allSelected ? allowed : old.filter(m => allowed.includes(m)));
        setViewSettingsError(null);
      } catch {
        if (active) { setAvailable([]); setViewSettingsError("Не удалось загрузить настройки маркетплейсов"); }
      } finally { if (active) setViewReady(true); }
    };
    void loadSettings();
    window.addEventListener("stock-view-updated", loadSettings);
    return () => { active = false; window.removeEventListener("stock-view-updated", loadSettings); };
  }, [allSelected]);
  const chooseDay = (date: string) => {
    if (!draftStart) { setDraftStart(date); return; }
    let start = draftStart, end = date;
    if (end < start) [start, end] = [end, start];
    if ((Date.parse(end) - Date.parse(start)) / 86400000 > 365) { setDraftStart(date); return; }
    setFrom(start); setTo(end); setDraftStart(null); setCalendarOpen(false); setTooltip(null);
  };
  const preset = (value: string) => {
    const today = new Date(); today.setHours(12, 0, 0, 0);
    let start = today, end = today;
    if (value === "yesterday") start = end = dateAdd(today, -1);
    if (value === "7") start = dateAdd(today, -6);
    if (value === "14") start = dateAdd(today, -13);
    if (value === "month") start = new Date(today.getFullYear(), today.getMonth(), 1, 12);
    if (value === "year") start = new Date(today.getFullYear(), 0, 1, 12);
    setFrom(dateString(start)); setTo(dateString(end)); setDraftStart(null); setCalendarOpen(false); setTooltip(null);
  };
  const calendarCells = Array.from({ length: Math.ceil(((calendarCursor.getDay() + 6) % 7 + monthDays(calendarCursor.getFullYear(), calendarCursor.getMonth())) / 7) * 7 }, (_, i) => {
    const offset = (calendarCursor.getDay() + 6) % 7;
    const day = i - offset + 1;
    return day > 0 && day <= monthDays(calendarCursor.getFullYear(), calendarCursor.getMonth()) ? dateString(new Date(calendarCursor.getFullYear(), calendarCursor.getMonth(), day, 12)) : null;
  });
  const invalid = !from || !to || to < from || (Date.parse(to) - Date.parse(from)) / 86400000 > 365;

  useEffect(() => {
    if (invalid) return;
    let active = true;
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      const result = await Promise.all(MARKETS.map(async market => {
        try {
          const query = new URLSearchParams({ date_from: from, date_to: to });
          const response = await fetch(`http://127.0.0.1:8000/analytics/${market.id === "wb" ? "wb-sales" : market.id === "ozon" ? "ozon-sales" : "yandex-sales"}?${query}`, { credentials: "include", signal: controller.signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const json: Series = await response.json();
          if (!Array.isArray(json.rows)) throw new Error("Некорректный ответ API");
          return { id: market.id, value: json } as const;
        } catch (error) {
          return { id: market.id, error: error instanceof Error ? error.message : "Ошибка загрузки" } as const;
        }
      }));
      // Сопоставимый предыдущий период той же длины, сдвинутый назад.
      const durationDays = Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1;
      const previousTo = dateString(dateAdd(new Date(`${from}T12:00:00`), -1));
      const previousFrom = dateString(dateAdd(new Date(`${from}T12:00:00`), -durationDays));
      const earlier = await Promise.all(MARKETS.map(async market => {
        try {
          const query = new URLSearchParams({ date_from: previousFrom, date_to: previousTo });
          const response = await fetch(`http://127.0.0.1:8000/analytics/${market.id === "wb" ? "wb-sales" : market.id === "ozon" ? "ozon-sales" : "yandex-sales"}?${query}`, { credentials: "include", signal: controller.signal });
          if (!response.ok) return { id: market.id, value: null } as const;
          const json: Series = await response.json();
          return { id: market.id, value: Array.isArray(json.rows) ? json : null } as const;
        } catch { return { id: market.id, value: null } as const; }
      }));
      const previousSeries: Partial<Record<Market, Series>> = {};
      earlier.forEach(item => { if (item.value) previousSeries[item.id] = item.value; });
      let previousEst: Estimate | null = null;
      try {
        const all: Estimate["rows"] = [];
        let cursor = new Date(`${previousFrom}T12:00:00`);
        const endDate = new Date(`${previousTo}T12:00:00`);
        while (cursor <= endDate) {
          const end = dateAdd(cursor, 90);
          const chunkEnd = end > endDate ? endDate : end;
          const query = new URLSearchParams({ date_from: dateString(cursor), date_to: dateString(chunkEnd) });
          const response = await fetch(`http://127.0.0.1:8000/analytics/ozon-order-estimate?${query}`, { credentials: "include", signal: controller.signal });
          if (!response.ok) throw new Error("История оценки Ozon недоступна");
          const json: Estimate = await response.json();
          if (!Array.isArray(json.rows)) throw new Error("Нет строк Ozon");
          all.push(...json.rows);
          cursor = dateAdd(chunkEnd, 1);
        }
        previousEst = { rows: all };
      } catch { previousEst = null; }
      // Endpoint Ozon разрешает максимум 91 календарный день за один запрос.
      // По длинным диапазонам запрашиваем непересекающиеся отрезки.
      let ozonEstimate: Estimate | null = null;
      let ozonEstimateError: string | null = null;
      try {
        const chunks: { date_from: string; date_to: string }[] = [];
        let start = new Date(`${from}T12:00:00`);
        const last = new Date(`${to}T12:00:00`);
        while (start <= last) {
          const end = new Date(start);
          end.setDate(end.getDate() + 90);
          if (end > last) end.setTime(last.getTime());
          chunks.push({ date_from: dateString(start), date_to: dateString(end) });
          start = new Date(end);
          start.setDate(start.getDate() + 1);
        }
        const allRows: Estimate["rows"] = [];
        for (const chunk of chunks) {
          const query = new URLSearchParams(chunk);
          const response = await fetch(`http://127.0.0.1:8000/analytics/ozon-order-estimate?${query}`, { credentials: "include", signal: controller.signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const json: Estimate = await response.json();
          if (!Array.isArray(json.rows)) throw new Error("Некорректный ответ Ozon");
          allRows.push(...json.rows);
        }
        ozonEstimate = { rows: allRows };
      } catch (error) {
        ozonEstimateError = error instanceof Error ? error.message : "Ошибка загрузки";
      }
      if (!active) return;
      setPriorData(previousSeries);
      setPriorEstimate(previousEst);
      setEstimate(ozonEstimate);
      setEstimateError(ozonEstimateError);
      const next: Partial<Record<Market, Series>> = {};
      const failed: Partial<Record<Market, string>> = {};
      result.forEach(item => { if ("value" in item && item.value) next[item.id] = item.value; else if ("error" in item) failed[item.id] = item.error; });
      setData(next); setErrors(failed); setLoading(false);
    };
    void load();
    return () => { active = false; controller.abort(); };
  }, [from, to, invalid]);

  const aggregated = useMemo(() => {
    const periods = new Map<string, Record<Market, { sum: number; units: number; cancels: number; covered: number; expected: number }>>();
    for (let t = new Date(`${from}T12:00:00`); t <= new Date(`${to}T12:00:00`); t.setDate(t.getDate() + 1)) {
      const day = dateString(t);
      const key = group === "month" ? day.slice(0, 7) : day;
      if (!periods.has(key)) periods.set(key, {
        wb: { sum: 0, units: 0, cancels: 0, covered: 0, expected: 0 },
        ozon: { sum: 0, units: 0, cancels: 0, covered: 0, expected: 0 },
        yandex: { sum: 0, units: 0, cancels: 0, covered: 0, expected: 0 },
      });
      const bucket = periods.get(key)!;
      for (const market of MARKETS) bucket[market.id].expected += 1;
    }
    const estimatedByDay = new Map((estimate?.rows ?? []).map(row => [row.date, Number(row.estimated_rub)]));
    for (const market of MARKETS) {
      for (const row of data[market.id]?.rows ?? []) {
        const key = group === "month" ? row.date.slice(0, 7) : row.date;
        const bucket = periods.get(key)?.[market.id];
        if (!bucket || row.loaded === false) continue;
        if (market.id === "ozon" && priceMode === "realization") {
          if (!estimatedByDay.has(row.date)) continue;
          bucket.sum += estimatedByDay.get(row.date) || 0;
        } else {
          bucket.sum += Number(row.revenue) || 0;
        }
        bucket.units += Number(row.ordered_units) || 0;
        if (market.id === "wb") bucket.cancels += Number(row.cancel_count) || 0;
        bucket.covered += 1;
      }
    }
    return [...periods].map(([key, values]) => ({ key, values }));
  }, [from, to, group, data, estimate, priceMode]);
  const previous = useMemo(() => {
    const duration = Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1;
    const earlier = dateAdd(new Date(`${from}T12:00:00`), -duration);
    const priorEstimateMap = new Map((priorEstimate?.rows ?? []).map(r => [r.date, Number(r.estimated_rub)]));
    const byMarket = {} as Record<Market, (number | null)[]>;
    for (const market of MARKETS) {
      const daily = new Map((priorData[market.id]?.rows ?? []).filter(r => r.loaded !== false).map(r => [r.date, r]));
      let elapsed = 0;
      byMarket[market.id] = aggregated.map(p => {
        const days = p.values[market.id].expected;
        let sum = 0, covered = 0;
        for (let i = 0; i < days; i++, elapsed++) {
          const day = dateString(dateAdd(earlier, elapsed));
          const row = daily.get(day);
          if (!row) continue;
          if (market.id === "ozon" && priceMode === "realization") {
            if (!priorEstimateMap.has(day)) continue;
            sum += priorEstimateMap.get(day) ?? 0;
          } else sum += Number(row.revenue) || 0;
          covered++;
        }
        return covered === days ? sum : null;
      });
    }
    return byMarket;
  }, [from, to, aggregated, priorData, priorEstimate, priceMode]);
  const graphHeight = 208;
  const interpolate = (points: { x: number; y: number }[]) => points.map((p,i) => `${i ? "L" : "M"}${p.x.toFixed(3)} ${p.y.toFixed(3)}`).join(" ");
  const selectedMarkets = MARKETS.filter(m => available.includes(m.id) && enabled.includes(m.id) && !!data[m.id]);
  // В режиме «Все» строим одну серию из суммы доступных площадок.
  // Если у одной из площадок нет данных, разрываем линию, а не рисуем неполную сумму.
  const currentSeries = useMemo(() => {
    if (!allSelected) return selectedMarkets.map(m => ({
      id: m.id, values: aggregated.map(period => period.values[m.id].covered > 0 ? period.values[m.id].sum : null),
    }));
    if (!selectedMarkets.length) return [];
    return [{ id: "all", values: aggregated.map(period => selectedMarkets.every(m =>
      period.values[m.id].covered === period.values[m.id].expected)
      ? selectedMarkets.reduce((sum, m) => sum + period.values[m.id].sum, 0) : null) }];
  }, [allSelected, aggregated, selectedMarkets.map(m => m.id).join(",")]);
  const previousSeries = useMemo(() => {
    if (!allSelected) return selectedMarkets.map(m => ({ id: m.id, values: previous[m.id] ?? [] }));
    if (!selectedMarkets.length) return [];
    return [{ id: "all", values: aggregated.map((_, i) => {
      const parts = selectedMarkets.map(m => previous[m.id]?.[i] ?? null);
      return parts.every((value): value is number => value !== null)
        ? (parts as number[]).reduce((sum, value) => sum + value, 0) : null;
    }) }];
  }, [allSelected, aggregated, previous, selectedMarkets.map(m => m.id).join(",")]);
  const graphCeiling = Math.max(1,
    ...currentSeries.flatMap(series => series.values.filter((v): v is number => v !== null)),
    ...(showPrevious ? previousSeries.flatMap(series => series.values.filter((v): v is number => v !== null)) : []));
  const currentLines = currentSeries.map(series => {
    const segments: string[] = [];
    const points: { x: number; y: number; key: string; value: number }[] = [];
    let run: { x: number; y: number }[] = [];
    series.values.forEach((value, i) => {
      if (value === null) {
        if (run.length > 1) segments.push(interpolate(run));
        run = [];
        return;
      }
      const point = { x: (i + .5) / series.values.length * 1000,
        y: graphHeight - value / graphCeiling * graphHeight,
        key: aggregated[i].key, value };
      run.push({ x: point.x, y: point.y });
      points.push(point);
    });
    if (run.length > 1) segments.push(interpolate(run));
    return { id: series.id, paths: segments, points };
  });
  const priorLines = previousSeries.map(series => {
    const segments: string[] = [];
    let run: { x: number; y: number }[] = [];
    series.values.forEach((value, i) => {
      if (value === null) {
        if (run.length > 1) segments.push(interpolate(run));
        run = [];
        return;
      }
      run.push({ x: (i + .5) / series.values.length * 1000, y: graphHeight - value / graphCeiling * graphHeight });
    });
    if (run.length > 1) segments.push(interpolate(run));
    return { id: series.id, paths: segments };
  });
  const selected = MARKETS.filter(m => available.includes(m.id) && enabled.includes(m.id) && !!data[m.id]);
  const totals = selected.reduce((acc, m) => {
    for (const period of aggregated) { acc.revenue += period.values[m.id].sum; acc.units += period.values[m.id].units; }
    return acc;
  }, { revenue: 0, units: 0 });
  const cancellationAvailable = available.includes("wb") && enabled.includes("wb") && !!data.wb && aggregated.every(p => p.values.wb.covered === p.values.wb.expected);
  const cancelTotal = available.includes("wb") && enabled.includes("wb") ? aggregated.reduce((sum, p) => sum + p.values.wb.cancels, 0) : 0;
  const hovered = aggregated.find(p => p.key === tooltip?.key);
  const missing = selected.some(m => aggregated.some(p => p.values[m.id].covered !== p.values[m.id].expected));

  return <section className="unified-sales">
    <div className="unified-sales-heading"><div><h2>Продажи · все маркетплейсы</h2><p>Показатель «Заказано», ₽ и шт. В режиме реализации пересчитывается только Ozon (оценка цены покупателя); WB и Яндекс без пересчёта.</p></div></div>
    <div className="unified-sales-controls">
      <div className="unified-range-wrap">
        <button type="button" className="unified-range-trigger" aria-expanded={calendarOpen} onClick={() => { setCalendarOpen(v => !v); setDraftStart(null); }}><svg className="unified-calendar-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8"/><path d="M7 3v4M17 3v4M3 10h18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg> {shortDate(from)} — {shortDate(to)}</button>
        {calendarOpen && <div className="unified-calendar" role="dialog" aria-label="Выбор периода">
          <div className="unified-presets">{[["today","Сегодня"],["yesterday","Вчера"],["7","7 дней"],["14","14 дней"],["month","Месяц"],["year","Год"]].map(([id,title]) => <button type="button" key={id} onClick={() => preset(id)}>{title}</button>)}</div>
          <div className="unified-calendar-main"><div className="unified-cal-header"><button aria-label="Предыдущий месяц" onClick={() => setCalendarCursor(new Date(calendarCursor.getFullYear(),calendarCursor.getMonth()-1,1))}>‹</button><b>{calendarCursor.toLocaleDateString("ru-RU", {month:"long",year:"numeric"})}</b><button aria-label="Следующий месяц" onClick={() => setCalendarCursor(new Date(calendarCursor.getFullYear(),calendarCursor.getMonth()+1,1))}>›</button></div>
            <div className="unified-cal-grid">{["Пн","Вт","Ср","Чт","Пт","Сб","Вс"].map(d=><span key={d} className="unified-cal-weekday">{d}</span>)}{calendarCells.map((d,i) => d ? <button key={d} type="button" className={[(d===draftStart || (!draftStart && (d===from || d===to))) ? "edge" : "", (!draftStart && d>from && d<to) ? "between" : ""].join(" ")} onClick={() => chooseDay(d)}>{Number(d.slice(-2))}</button> : <span key={i}/> )}</div>
            <p>{draftStart ? `Начало: ${shortDate(draftStart)}. Выберите конец (можно ту же дату).` : "Выберите первую и последнюю дату периода"}</p>
          </div>
        </div>}
      </div>
      <div className="unified-sales-segment"><button className={group === "day" ? "active" : ""} onClick={() => setGroup("day")}>По дням</button><button className={group === "month" ? "active" : ""} onClick={() => setGroup("month")}>По месяцам</button></div>
      <div className="unified-sales-segment" role="group" aria-label="Метод расчёта суммы">
        <button type="button" className={priceMode === "seller" ? "active" : ""} aria-pressed={priceMode === "seller"} onClick={() => setPriceMode("seller")}>По цене продавца</button>
        <button type="button" className={priceMode === "realization" ? "active" : ""} aria-pressed={priceMode === "realization"} onClick={() => setPriceMode("realization")}>По цене реализации</button>
      </div>
      <div className="unified-sales-markets" role="group" aria-label="Выбор маркетплейсов">
        <button type="button" className={allSelected ? "active" : ""} aria-pressed={allSelected} onClick={() => { setAllSelected(true); setEnabled(available); }}>Все</button>
        {MARKETS.filter(m => available.includes(m.id)).map(m => <button type="button" key={m.id} className={!allSelected && enabled.includes(m.id) ? "active" : ""} aria-pressed={!allSelected && enabled.includes(m.id)} onClick={() => {
          if (allSelected) { setAllSelected(false); setEnabled([m.id]); }
          else setEnabled(old => old.includes(m.id) ? old.filter(x => x !== m.id) : [...old, m.id]);
        }}>{m.title}</button>)}
        <button type="button" className={`unified-previous-toggle ${showPrevious ? "active" : ""}`} aria-pressed={showPrevious} onClick={() => setShowPrevious(v => !v)}>Прошлый период</button>
      </div>
    </div>
    {invalid ? <p role="alert">Выберите правильный период не более 366 дней.</p> : <>
      <div className="unified-sales-summary"><div><span>Заказано на сумму</span><strong>{money(totals.revenue)}</strong></div><div><span>Заказано товаров</span><strong>{totals.units.toLocaleString("ru-RU")} шт.</strong></div><div className="unified-metric-info" tabIndex={0} onMouseEnter={() => setMetricTip("cancels")} onMouseLeave={() => setMetricTip(null)} onFocus={() => setMetricTip("cancels")} onBlur={() => setMetricTip(null)}><span>Отмены</span><strong>{cancellationAvailable ? `${cancelTotal.toLocaleString("ru-RU")} шт.` : "Нет данных"}</strong><small>Доступные данные по площадкам</small>{metricTip === "cancels" && <div className="unified-metric-tooltip"><b>Отмены по МП</b><div>WB: {enabled.includes("wb") && available.includes("wb") ? (cancellationAvailable ? `${cancelTotal.toLocaleString("ru-RU")} шт.` : "Не все дни загружены") : "Не выбран"}</div><div>Ozon: {enabled.includes("ozon") && available.includes("ozon") ? "Нет данных" : "Не выбран"}</div><div>Яндекс Маркет: {enabled.includes("yandex") && available.includes("yandex") ? "Нет данных" : "Не выбран"}</div></div>}</div><div className="unified-metric-info" tabIndex={0} onMouseEnter={() => setMetricTip("returns")} onMouseLeave={() => setMetricTip(null)} onFocus={() => setMetricTip("returns")} onBlur={() => setMetricTip(null)}><span>Возвраты</span><strong>Нет данных</strong><small>Сопоставимый показатель пока не подключён</small>{metricTip === "returns" && <div className="unified-metric-tooltip"><b>Возвраты по МП</b>{MARKETS.filter(m => available.includes(m.id) && enabled.includes(m.id)).map(m => <div key={m.id}>{m.title}: Нет данных</div>)}</div>}</div></div>
      {!viewReady && <p role="status">Загрузка настроек маркетплейсов…</p>}
      {viewSettingsError && <p role="alert">{viewSettingsError}</p>}
      {loading && <p role="status">Загрузка продаж…</p>}
      {Object.entries(errors).map(([id, message]) => <p role="alert" key={id}>Не удалось загрузить {MARKETS.find(m => m.id === id)?.title}: {message}</p>)}
      {priceMode === "realization" && enabled.includes("ozon") && <p className="unified-sales-warning">Ozon: расчётная цена покупателя из FBO/FBS с конвертацией валют; включает отмены, не является официальным показателем Ozon «По цене реализации». Для WB и Яндекса суммы не пересчитываются.</p>}
      {priceMode === "realization" && enabled.includes("ozon") && estimateError && <p role="alert">Не удалось получить оценку Ozon: {estimateError}. Сумма Ozon без подмены исходной ценой.</p>}
      {missing && <p className="unified-sales-warning">За часть дней данные отсутствуют. Суммы рассчитаны только по загруженным дням; незагруженные дни не считаются нулевыми продажами.</p>}
      {!enabled.length && <p>Выберите хотя бы один маркетплейс.</p>}
      <div className="unified-chart-layout">
        <div className="unified-sales-scroll"><div className="unified-sales-chart" style={{ minWidth: `${Math.max(620, aggregated.length * (group === "day" ? 27 : 74))}px` }}>
          <svg className="unified-sales-lines" viewBox={`0 0 1000 ${graphHeight}`} preserveAspectRatio="none" aria-hidden="true">
            {currentLines.flatMap(line => line.paths.map((path, i) => <path key={`current-${line.id}-${i}`} className={`unified-current-line ${line.id}`} d={path}/>))}
            {currentLines.flatMap(line => line.points.map(point => <circle key={`point-${line.id}-${point.key}`} className={`unified-current-point ${line.id}`} cx={point.x} cy={point.y} r={tooltip?.key === point.key ? "3.7" : "2.3"}/>))}
            {showPrevious && priorLines.flatMap(line => line.paths.map((path, i) => <path key={`previous-${line.id}-${i}`} d={path} className={`unified-previous-line ${line.id}`} />))}
          </svg>
          <div className="unified-sales-bars">
            {aggregated.map(period => <div className="unified-sales-column" key={period.key}
              onMouseMove={e => { const x = Math.min(e.clientX + 16, window.innerWidth - 255); const y = Math.min(e.clientY + 14, window.innerHeight - 165); setTooltip({ key: period.key, x, y }); }}
              onMouseLeave={() => setTooltip(null)}>
              <small>{group === "day" ? `${Number(period.key.slice(8, 10))}.${Number(period.key.slice(5, 7))}` : period.key.slice(5) + "." + period.key.slice(0, 4)}</small>
            </div>)}
          </div>
        </div></div>
        <div className="unified-prior-legend" aria-label="Линии предыдущего периода">
          <b>Серии на графике</b>
          {allSelected
            ? <div className="unified-prior-legend-item"><span className="unified-legend-line all"/><span>Все маркетплейсы</span></div>
            : selected.map(m => <div key={m.id} className="unified-prior-legend-item"><span className={`unified-legend-line ${m.id}`}/><span>{m.title}</span></div>)}
          <small>{showPrevious ? "Сплошная линия — текущий период, пунктир — предыдущий период той же длины. При неполных данных линия прерывается." : "Сплошная линия — выбранный период."}</small>
        </div>
      </div>
      <p className="unified-sales-footnote">График показывает сумму заказов по выбранным площадкам; это не фактическая прибыль и не сумма выплат. Отсутствующие дни не добавляются к итогам. В режиме реализации количество товаров для Ozon берётся из аналитики заказов только за дни, для которых доступна оценка.</p>
    </>}
    {tooltip && hovered && <div className="unified-sales-tooltip" style={{ left: tooltip.x, top: tooltip.y }}>
      <strong>{group === "day" ? shortDate(hovered.key) : hovered.key.slice(5) + "." + hovered.key.slice(0, 4)}</strong>
      {selected.map(m => <div key={m.id}><span className="unified-tooltip-market"><i className={`unified-color-square ${m.id}`}/>{m.title}</span><b>{hovered.values[m.id].covered ? money(hovered.values[m.id].sum) : "Нет данных"}</b><small>{hovered.values[m.id].units.toLocaleString("ru-RU")} шт.</small></div>)}
      <div className="unified-sales-tooltip-total"><span>Всего</span><b>{money(selected.reduce((sum, m) => sum + hovered.values[m.id].sum, 0))}</b></div>
    </div>}
  </section>;
}
