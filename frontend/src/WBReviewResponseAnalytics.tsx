import { useEffect, useMemo, useState } from "react";
import Loader from "./components/Loader";

type Granularity = "month" | "day";
type Marketplace = "all" | "wb" | "yandex";
type Kind = "reviews" | "questions";

interface Trend {
  period: string;
  answered: number;
  active: number;
  timers: number;
  average_minutes: number;
  median_minutes: number;
}

interface RecordItem {
  marketplace: "wb" | "yandex";
  kind: Kind;
  id: string;
  created_at: string | null;
  monitored_from_at?: string | null;
  answered_detected_at?: string | null;
  resolution: string | null;
  baseline: boolean;
  last_seen_unanswered_at: string | null;
  left_unanswered_at: string | null;
  response_minutes: number | null;
  monitor_elapsed_minutes: number | null;
}

interface Data {
  status: string;
  average_human: string | null;
  average_minutes: number | null;
  median_minutes: number | null;
  answered_with_timing: number;
  timers_measured: number;
  timers_average_minutes: number | null;
  timers_median_minutes: number | null;
  pending_tracked: number;
  active_unanswered: number;
  pending_verification: number;
  queue_age_median_minutes: number | null;
  queue_age_average_minutes: number | null;
  queue_age_max_minutes: number | null;
  queue_age_measured: number;
  queue_age_distribution: { label: string; count: number }[];
  answered_observed: number;
  baseline_records: number;
  tracked_total: number;
  trend: Trend[];
  completed_trend: Trend[];
  items: RecordItem[];
  items_total: number;
  limit: number;
  offset: number;
}

interface HoverState {
  period: string;
  average_minutes: number;
  median_minutes: number;
  answered: number;
  active: number;
  timers: number;
  x: number;
  y: number;
}

const fmt = (m: number | null | undefined) => {
  if (m == null) return "—";
  if (m >= 60) return `${(m / 60).toFixed(1)} ч`;
  return `${Math.round(m)} мин`;
};

const periodLabel = (period: string, granularity: Granularity) => {
  const parts = period.split("-");
  if (granularity === "day" && parts.length === 3) return `${parts[2]}.${parts[1]}`;
  if (granularity === "month" && parts.length >= 2) return `${parts[1]}.${parts[0].slice(-2)}`;
  return period;
};

const fullPeriodLabel = (period: string, granularity: Granularity) => {
  const parts = period.split("-");
  if (granularity === "day" && parts.length === 3) {
    return `${parts[2]}.${parts[1]}.${parts[0]}`;
  }
  if (granularity === "month" && parts.length >= 2) {
    return `${parts[1]}.${parts[0].slice(-2)}`;
  }
  return period;
};

const bands = [
  { label: "0–12 ч", lower: 0, upper: 720 },
  { label: "12–24 ч", lower: 720, upper: 1440 },
  { label: "24–48 ч", lower: 1440, upper: 2880 },
  { label: "48 ч и более", lower: 2880, upper: Infinity },
];

export default function WBReviewResponseAnalytics() {
  const [data, setData] = useState<Data | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [granularity, setGranularity] = useState<Granularity>("day");
  const [marketplace, setMarketplace] = useState<Marketplace>("all");
  const [kind, setKind] = useState<Kind>("reviews");
  const [measuredMinutes, setMeasuredMinutes] = useState<number[]>([]);
  const [hover, setHover] = useState<HoverState | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setRefreshTick((v) => v + 1), 60000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setHover(null);

    const load = async () => {
      const pageSize = 500;
      const params = new URLSearchParams({
        marketplace,
        kind,
        granularity,
        limit: String(pageSize),
        offset: "0",
      });
      const endpoint = `http://127.0.0.1:8000/analytics/response-monitoring?`;
      const getPage = async (offset: number): Promise<Data> => {
        params.set("offset", String(offset));
        const response = await fetch(`${endpoint}${params}`, {
          credentials: "include",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Ошибка API: HTTP ${response.status}`);
        return response.json() as Promise<Data>;
      };

      try {
        const first = await getPage(0);
        const minutes = first.items
          .filter((item) => item.monitor_elapsed_minutes != null)
          .map((item) => item.monitor_elapsed_minutes as number);

        for (let offset = pageSize; offset < first.items_total; offset += pageSize) {
          if (controller.signal.aborted) return;
          const page = await getPage(offset);
          minutes.push(...page.items
            .filter((item) => item.monitor_elapsed_minutes != null)
            .map((item) => item.monitor_elapsed_minutes as number));
        }

        if (!controller.signal.aborted) {
          setData(first);
          setMeasuredMinutes(minutes);
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(e instanceof Error ? e.message : "Не удалось загрузить статистику");
          setData(null);
          setMeasuredMinutes([]);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };

    void load();
    return () => controller.abort();
  }, [granularity, marketplace, kind, refreshTick]);

  const visible = useMemo(
    () => data?.trend.slice(-(granularity === "month" ? 12 : 31)) ?? [],
    [data, granularity],
  );

  const maxAverage = Math.max(...visible.map((item) => item.average_minutes), 1);
  const selectedMinutes = measuredMinutes;
  const distribution = useMemo(
    () => bands.map((band) => {
      const count = selectedMinutes.filter((minutes) => minutes >= band.lower && minutes < band.upper).length;
      return { ...band, count, percent: selectedMinutes.length ? count / selectedMinutes.length * 100 : 0 };
    }), [selectedMinutes],
  );

  return (
    <section className="wb-response-section">
      <div className="wb-response-header">
        <div>
          <h2>Время обработки отзывов и вопросов</h2>
          <p>
            WB и Яндекс Маркет. Учитываются уже обработанные и ожидающие ответа обращения.
            Время отсчитывается с момента попадания в мониторинг до подтверждённого ответа; у неотвеченных оно продолжает расти. Для Яндекс Маркета отзывы без
            текста, тегов и медиа исключаются.
          </p>
        </div>
        <div className="wb-response-switch" role="group" aria-label="Группировка">
          <button
            type="button"
            className={granularity === "day" ? "active" : ""}
            onClick={() => setGranularity("day")}
          >
            По дням
          </button>
          <button
            type="button"
            className={granularity === "month" ? "active" : ""}
            onClick={() => setGranularity("month")}
          >
            По месяцам
          </button>
        </div>
      </div>

      <div className="response-monitor-filters">
        <div className="response-monitor-filter">
          <span>Маркетплейс</span>
          <div className="wb-response-switch" role="group" aria-label="Маркетплейс">
            {([
              { value: "all", label: "Все" },
              { value: "wb", label: "WB" },
              { value: "yandex", label: "Яндекс Маркет" },
            ] as const).map((variant) => (
              <button
                key={variant.value}
                type="button"
                className={marketplace === variant.value ? "active" : ""}
                onClick={() => setMarketplace(variant.value)}
              >
                {variant.label}
              </button>
            ))}
          </div>
        </div>

        <div className="response-monitor-filter">
          <span>Тип обращения</span>
          <div className="wb-response-switch" role="group" aria-label="Тип обращения">
            <button
              type="button"
              className={kind === "reviews" ? "active" : ""}
              onClick={() => setKind("reviews")}
            >
              Отзывы
            </button>
            <button
              type="button"
              className={kind === "questions" ? "active" : ""}
              onClick={() => setKind("questions")}
            >
              Вопросы
            </button>
          </div>
        </div>
      </div>

      {loading && (
        <div className="response-monitor-status">
          <Loader size="small" /> Обновление статистики...
        </div>
      )}

      {error && (
        <div className="response-monitor-error">
          Не удалось получить статистику: {error}. Проверь авторизацию и наличие
          <code> /analytics/response-monitoring</code> в backend.
        </div>
      )}

      {data && (
        <>
          <div className="wb-response-kpi-grid wb-response-kpi-grid--five">
            <article className="wb-response-kpi">
              <span>Среднее время обработки обращения</span>
              <strong>{fmt(data.timers_average_minutes)}</strong>
            </article>
            <article className="wb-response-kpi">
              <span>Обращений в расчёте</span>
              <strong>{data.timers_measured.toLocaleString("ru-RU")}</strong>
            </article>
            <article className="wb-response-kpi">
              <span>Ожидают ответа</span>
              <strong>{data.active_unanswered.toLocaleString("ru-RU")}</strong>
            </article>
            <article className="wb-response-kpi">
              <span>Проверяем ответ</span>
              <strong>{data.pending_verification.toLocaleString("ru-RU")}</strong>
            </article>
          </div>

          <p className="response-monitor-caption">
            Завершённые обращения: таймер остановлен после подтверждения ответа; без ответа: время продолжает идти.
            Обработано с расчётом: {data.answered_with_timing.toLocaleString("ru-RU")}.
          </p>

          <div className="wb-response-body response-monitor-body">
            <div className="wb-response-panel">
              <div className="wb-response-subtitle">Динамика среднего времени обработки</div>
              {visible.length ? (
                <div className="wb-response-bars">
                  {visible.map((item) => (
                    <div
                      className="wb-response-bar-item"
                      key={item.period}
                      onMouseMove={(event) => {
                        const tooltipWidth = 220;
                        const tooltipHeight = 102;
                        const gap = 16;
                        const margin = 8;
                        const x = event.clientX + gap + tooltipWidth + margin <= window.innerWidth
                          ? event.clientX + gap
                          : Math.max(margin, event.clientX - gap - tooltipWidth);
                        const y = Math.max(
                          margin,
                          Math.min(event.clientY - tooltipHeight / 2, window.innerHeight - tooltipHeight - margin),
                        );
                        setHover({
                          period: item.period,
                          average_minutes: item.average_minutes,
                          median_minutes: item.median_minutes,
                          answered: item.answered,
                          active: item.active,
                          timers: item.timers,
                          x,
                          y,
                        });
                      }}
                      onMouseLeave={() => setHover(null)}
                    >
                      <div className="wb-response-bar-value">{fmt(item.average_minutes)}</div>
                      <div className="wb-response-bar-track">
                        <div
                          className="wb-response-bar-fill"
                          style={{ height: `${Math.max(6, (item.average_minutes / maxAverage) * 100)}%` }}
                        />
                      </div>
                      <div className="wb-response-bar-label">{periodLabel(item.period, granularity)}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="wb-response-empty">Пока нет обращений с рассчитанным временем.</div>
              )}
            </div>

            <div className="wb-response-panel">
              <div className="wb-response-subtitle">Распределение времени обработки</div>
              <div className="wb-response-distribution">
                {distribution.map((band) => (
                  <div key={band.label}>
                    <div className="wb-response-distribution-label">
                      <span>{band.label}</span>
                      <strong>
                        {band.percent.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%
                      </strong>
                    </div>
                    <div
                      className="wb-response-distribution-track"
                      role="progressbar"
                      aria-valuenow={band.percent}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={band.label}
                    >
                      <div
                        className="wb-response-distribution-fill"
                        style={{ width: `${band.percent}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              <p className="response-monitor-caption">
                Доли от {selectedMinutes.length.toLocaleString("ru-RU")} обращений (обработанных и ожидающих ответа).
              </p>
            </div>
          </div>

          <p className="response-monitor-caption">
            График показывает среднее время обработки по дате попадания обращения в мониторинг.
            По дням — <strong>12.10</strong>, по месяцам — <strong>10.26</strong>.
          </p>
        </>
      )}

      {hover && (
        <div
          className="response-monitor-cursor-tooltip"
          role="tooltip"
          style={{ left: hover.x, top: hover.y }}
        >
          <span>{fullPeriodLabel(hover.period, granularity)}</span>
          <strong>{fmt(hover.average_minutes)}</strong>
          <div className="response-monitor-cursor-tooltip-grid">
            <span>Медиана</span>
            <span>{fmt(hover.median_minutes)}</span>
            <span>Без ответа</span>
            <span>{hover.timers.toLocaleString("ru-RU")}</span>
            <span>Обработано</span>
            <span>{hover.answered.toLocaleString("ru-RU")}</span>
          </div>
        </div>
      )}
    </section>
  );
}
