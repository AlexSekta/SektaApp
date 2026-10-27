import { useEffect, useMemo, useRef, useState } from "react";

interface DateFilterProps {
  value: string;
  onChange: (value: string) => void;
  min?: string;
  ariaLabel?: string;
}

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
];

function parseDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatValue(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function DateFilter({ value, onChange, min, ariaLabel }: DateFilterProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const selected = parseDate(value);
  const minimum = parseDate(min || "");
  const [open, setOpen] = useState(false);
  const [viewDate, setViewDate] = useState(() => {
    const base = selected || minimum || new Date();
    return new Date(base.getFullYear(), base.getMonth(), 1);
  });

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  useEffect(() => {
    if (selected) setViewDate(new Date(selected.getFullYear(), selected.getMonth(), 1));
  }, [value]);

  const days = useMemo(() => {
    const first = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);
    const offset = (first.getDay() + 6) % 7;
    const count = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 0).getDate();
    const cells: Array<Date | null> = Array(offset).fill(null);
    for (let day = 1; day <= count; day += 1) {
      cells.push(new Date(viewDate.getFullYear(), viewDate.getMonth(), day));
    }
    while (cells.length % 7) cells.push(null);
    return cells;
  }, [viewDate]);

  const canGoPrevious = !minimum ||
    new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1) >=
    new Date(minimum.getFullYear(), minimum.getMonth(), 1);

  return (
    <div ref={ref} className={`reviews-date-picker${open ? " is-open" : ""}`}>
      <button
        type="button"
        className="reviews-date-trigger"
        aria-label={ariaLabel}
        aria-expanded={open}
        onClick={() => setOpen(current => !current)}
      >
        <span className={value ? "reviews-date-value" : "reviews-date-placeholder"}>
          {value ? value.split("-").reverse().join(".") : "Выберите дату"}
        </span>
        <span className="reviews-date-icon" aria-hidden="true" />
      </button>

      {open && (
        <div className="reviews-date-menu">
          <div className="reviews-date-nav">
            <button
              type="button"
              className="reviews-date-nav-button"
              disabled={!canGoPrevious}
              onClick={() => setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1))}
              aria-label="Предыдущий месяц"
            >
              ‹
            </button>
            <span>{MONTHS[viewDate.getMonth()]} {viewDate.getFullYear()}</span>
            <button
              type="button"
              className="reviews-date-nav-button"
              onClick={() => setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1))}
              aria-label="Следующий месяц"
            >
              ›
            </button>
          </div>

          <div className="reviews-date-weekdays">
            {WEEKDAYS.map(day => <span key={day}>{day}</span>)}
          </div>

          <div className="reviews-date-grid">
            {days.map((date, index) => {
              if (!date) return <span key={`empty-${index}`} className="reviews-date-empty" />;
              const current = formatValue(date);
              const isSelected = current === value;
              const isDisabled = Boolean(minimum && date < minimum);
              return (
                <button
                  type="button"
                  key={current}
                  className={`reviews-date-day${isSelected ? " selected" : ""}`}
                  disabled={isDisabled}
                  onClick={() => {
                    onChange(current);
                    setOpen(false);
                  }}
                >
                  {date.getDate()}
                </button>
              );
            })}
          </div>

          {value && (
            <button
              type="button"
              className="reviews-date-clear"
              onClick={() => {
                onChange("");
                setOpen(false);
              }}
            >
              Очистить
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default DateFilter;
