import { useEffect, useRef, useState } from "react";
import Loader from "./components/Loader";
import Toast, { type ToastType } from "./components/Toast";
import "./Reviews.css";
import DateFilter from "./DateFilter";

type Status = "unanswered" | "rating_only" | "answered" | "all";

interface YandexComment {
  id: number | null;
  text: string;
  author: string;
  author_type?: string | null;
  status?: string | null;
  can_modify?: boolean;
  parent_id?: number | null;
}

interface YandexReview {
  id: string;
  created_at: string | null;
  need_reaction: boolean;
  is_answered: boolean;
  author: string;
  offer_id?: string | null;
  product_name?: string | null;
  order_id?: number | null;
  advantages: string;
  disadvantages: string;
  comment: string;
  rating: number | null;
  comments_count: number;
  recommended: boolean | null;
  paid_amount: number;
  photos: string[];
  videos: string[];
  comments: YandexComment[];
  seller_comments: YandexComment[];
}

interface ResponseData {
  status: string;
  message?: string;
  business_id?: number;
  reviews: YandexReview[];
  next_page_token?: string | null;
  total_count?: number;
  count_filtered?: number;
  count_unanswered?: number;
}

function formatDate(value: string | null) {
  if (!value) return "Дата не указана";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit"
  });
}

function Stars({ value }: { value: number | null }) {
  if (!value) return <span className="review-rating-empty">Без оценки</span>;
  return (
    <span className="review-stars">
      {"★".repeat(value)}
      <span className="review-stars-muted">
        {"★".repeat(Math.max(0, 5 - value))}
      </span>
    </span>
  );
}


type SelectOption<T extends string> = { value: T; label: string };

function CustomSelect<T extends string>({
  value,
  options,
  onChange,
  className = "",
  ariaLabel,
}: {
  value: T;
  options: SelectOption<T>[];
  onChange: (value: T) => void;
  className?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const selected = options.find(option => option.value === value) || options[0];

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div
      ref={ref}
      className={`reviews-custom-select ${className}${open ? " is-open" : ""}`}
    >
      <button
        type="button"
        className="reviews-custom-select-trigger"
        aria-label={ariaLabel}
        aria-expanded={open}
        onClick={() => setOpen(current => !current)}
      >
        <span className="reviews-custom-select-value">{selected?.label ?? ""}</span>
        <span className="reviews-custom-select-arrow" aria-hidden="true" />
      </button>

      {open && (
        <div className="reviews-custom-select-menu">
          {options.map(option => (
            <button
              type="button"
              key={option.value}
              className={`reviews-custom-select-option${option.value === value ? " selected" : ""}`}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
            >
              <span>{option.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const UNANSWERED_FROM = "2026-01-01";

type ReviewFilters = {
  dateFrom: string;
  dateTo: string;
  rating: string;
  article: string;
};

const emptyFilters = (): ReviewFilters => ({
  dateFrom: "",
  dateTo: "",
  rating: "",
  article: "",
});

const filtersForStatus = (status: Status, filters: ReviewFilters): ReviewFilters => ({
  ...filters,
  dateFrom:
    status === "unanswered"
      ? (!filters.dateFrom || filters.dateFrom < UNANSWERED_FROM ? UNANSWERED_FROM : filters.dateFrom)
      : filters.dateFrom,
});

function YandexReviews() {
  const [status, setStatus] = useState<Status>("unanswered");
  const [reviews, setReviews] = useState<YandexReview[]>([]);
  const [unanswered, setUnanswered] = useState<number | null>(null);
  const [countFiltered, setCountFiltered] = useState(0);
  const [filters, setFilters] = useState<ReviewFilters>(() => emptyFilters());
  const [appliedFilters, setAppliedFilters] = useState<ReviewFilters>(() => emptyFilters());
  const [loading, setLoading] = useState(false);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [businessId, setBusinessId] = useState<number | null>(null);
  const [processingReviewId, setProcessingReviewId] = useState<string | null>(null);
  const [replyTexts, setReplyTexts] = useState<Record<string, string>>({});
  const [showScrollTop, setShowScrollTop] = useState(false);
  const [toast, setToast] = useState<{ type: ToastType; message: string } | null>(null);
  const [copiedValue, setCopiedValue] = useState<string | null>(null);

  const loadCount = async () => {
    try {
      const response = await fetch("http://127.0.0.1:8000/yandex/reviews/count");
      if (!response.ok) return;
      const data = await response.json();
      const count = Number(data.count_unanswered);
      if (data.status === "ok" && Number.isFinite(count) && count >= 0) {
        setUnanswered(count);
      }
    } catch {
      // Счётчик не должен ломать загрузку отзывов.
    }
  };

  const loadReviews = async (
    nextStatus: Status = status,
    pageToken: string | null = null,
    append = false,
    nextFilters = appliedFilters
  ) => {
    setLoading(true);
    try {
      const effectiveFilters = filtersForStatus(nextStatus, nextFilters);
      const params = new URLSearchParams({ status: nextStatus, limit: "100" });
      if (pageToken) params.set("page_token", pageToken);
      if (effectiveFilters.dateFrom) params.set("date_from", effectiveFilters.dateFrom);
      if (effectiveFilters.dateTo) params.set("date_to", effectiveFilters.dateTo);
      if (effectiveFilters.rating) params.set("rating", effectiveFilters.rating);
      if (effectiveFilters.article.trim()) params.set("article", effectiveFilters.article.trim());

      const response = await fetch(`http://127.0.0.1:8000/yandex/reviews?${params.toString()}`);
      const data = await response.json() as ResponseData;
      if (!response.ok || data.status !== "ok") {
        throw new Error(data.message || `Ошибка сервера: ${response.status}`);
      }
      setReviews(current => append ? [...current, ...(data.reviews || [])] : (data.reviews || []));
      setNextPageToken(data.next_page_token || null);
      setBusinessId(data.business_id || null);
      setUnanswered(Number.isFinite(Number(data.count_unanswered)) ? Number(data.count_unanswered) : null);
      setCountFiltered(Number(data.count_filtered ?? data.total_count) || 0);
    } catch (error) {
      setToast({
        type: "error",
        message: error instanceof Error ? error.message : "Не удалось загрузить отзывы Яндекс Маркета"
      });
    } finally {
      setLoading(false);
    }
  };

  const copyValue = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      const key = `${label}:${value}`;
      setCopiedValue(key);
      window.setTimeout(() => {
        setCopiedValue(current => current === key ? null : current);
      }, 2500);
    } catch {
      setToast({ type: "error", message: `Не удалось скопировать ${label}` });
    }
  };

  const toggleProcessing = (reviewId: string) => {
    setProcessingReviewId(current => current === reviewId ? null : reviewId);
  };

  const setReplyText = (reviewId: string, value: string) => {
    setReplyTexts(current => ({ ...current, [reviewId]: value }));
  };

  const canSendReply = (reviewId: string) =>
    (replyTexts[reviewId] || "").trim().length >= 50;

  const refresh = async () => {
    const nextFilters = filtersForStatus(status, appliedFilters);
    await Promise.all([loadReviews(status, null, false, nextFilters), loadCount()]);
  };

  useEffect(() => {
    const initialFilters = filtersForStatus("unanswered", emptyFilters());
    setFilters(initialFilters);
    setAppliedFilters(initialFilters);
    void Promise.all([loadReviews("unanswered", null, false, initialFilters), loadCount()]);
  }, []);

  useEffect(() => {
    const onScroll = () => setShowScrollTop(window.scrollY > 300);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const changeStatus = (value: Status) => {
    const nextFilters = filtersForStatus(value, appliedFilters);
    setStatus(value);
    setFilters(nextFilters);
    setAppliedFilters(nextFilters);
    setNextPageToken(null);
    setProcessingReviewId(null);
    void loadReviews(value, null, false, nextFilters);
  };

  return (
    <div className="reviews-page">
      <div className="reviews-header">
        <div>
          <h1>Отзывы и вопросы</h1>
          <p>Отзывы покупателей Яндекс Маркета.{businessId ? ` Кабинет: ${businessId}.` : ""}</p>
        </div>
      </div>

      <div className="reviews-toolbar">
        <div className="reviews-tabs">
          {([
            ["unanswered", "Без ответа"],
            ["rating_only", "Только оценка"],
            ["answered", "С ответом"],
            ["all", "Все отзывы"],
          ] as const).map(([value, label]) => (
            <button
              type="button"
              key={value}
              className={status === value ? "reviews-tab active" : "reviews-tab"}
              onClick={() => changeStatus(value)}
            >
              <span>{label}</span>
              {value === "unanswered" && unanswered !== null && (
                <span className="reviews-tab-count">{unanswered}</span>
              )}
            </button>
          ))}
        </div>
        <div className="reviews-result-count">
          {countFiltered} отзывов
        </div>
        <button type="button" className="reviews-refresh" onClick={() => void refresh()} disabled={loading}>
          {loading ? <><Loader size="small" />Загрузка...</> : "Обновить"}
        </button>
      </div>

      <div className="reviews-filters">
        <label className="reviews-filter-field reviews-filter-date">
          <span>Дата от</span>
          <DateFilter
            value={filters.dateFrom}
            min={status === "unanswered" ? UNANSWERED_FROM : undefined}
            onChange={value => setFilters(current => ({ ...current, dateFrom: value }))}
          />
        </label>

        <label className="reviews-filter-field reviews-filter-date">
          <span>Дата до</span>
          <DateFilter
            value={filters.dateTo}
            onChange={value => setFilters(current => ({ ...current, dateTo: value }))}
          />
        </label>

        <label className="reviews-filter-field">
          <span>Рейтинг</span>
          <CustomSelect
            className="reviews-filter-select"
            ariaLabel="Фильтр по рейтингу"
            value={filters.rating}
            onChange={value => setFilters(current => ({ ...current, rating: value }))}
            options={[
              { value: "", label: "Все рейтинги" },
              { value: "5", label: "5 ★" },
              { value: "4", label: "4 ★" },
              { value: "3", label: "3 ★" },
              { value: "2", label: "2 ★" },
              { value: "1", label: "1 ★" },
            ]}
          />
        </label>

        <label className="reviews-filter-field reviews-filter-article">
          <span>Артикул продавца</span>
          <input
            type="text"
            value={filters.article}
            onChange={event => setFilters(current => ({ ...current, article: event.target.value }))}
            placeholder="Введите артикул"
          />
        </label>

        <div className="reviews-filter-actions">
          <button
            type="button"
            className="reviews-filter-apply"
            onClick={() => {
              const nextFilters = filtersForStatus(status, filters);
              setFilters(nextFilters);
              setAppliedFilters(nextFilters);
              setNextPageToken(null);
              void loadReviews(status, null, false, nextFilters);
            }}
            disabled={loading}
          >
            Применить
          </button>
          <button
            type="button"
            className="reviews-filter-reset"
            onClick={() => {
              const nextFilters = filtersForStatus(status, emptyFilters());
              setFilters(nextFilters);
              setAppliedFilters(nextFilters);
              setNextPageToken(null);
              void loadReviews(status, null, false, nextFilters);
            }}
            disabled={loading}
          >
            Сбросить
          </button>
        </div>

      </div>

      {loading && reviews.length === 0 ? (
        <div className="reviews-loading"><Loader size="small" /><span>Получаем отзывы Яндекс Маркета...</span></div>
      ) : reviews.length === 0 ? (
        <div className="reviews-empty">Отзывов по выбранному фильтру нет.</div>
      ) : (
        <div className="reviews-list">
          {reviews.map(review => (
            <article className="review-card" key={review.id}>
              <div className="review-card-columns">
                <div className="review-card-left">
                  <div className="review-product-name">
                    {review.product_name || review.offer_id || "Товар Яндекс Маркета"}
                  </div>

                  <div className="review-product-meta">
                    <span>Артикул: {review.offer_id || "Без артикула"}</span>
                    {review.offer_id && (
                      <span className="review-nmid">
                        {/* <button
                          type="button"
                          className="review-copy-button"
                          onClick={() => void copyValue(review.offer_id!, "article")}
                          aria-label={`Скопировать артикул ${review.offer_id}`}
                          title="Скопировать артикул"
                        >
                          <svg className="review-copy-icon" viewBox="0 0 24 24" aria-hidden="true">
                            <rect x="8" y="8" width="11" height="11" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
                            <path d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4H6.5A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                          </svg>
                        </button> */}
                        <span className={copiedValue === `article:${review.offer_id}` ? "review-copy-success visible" : "review-copy-success"}>Скопировано</span>
                      </span>
                    )}

                    {review.order_id !== null && review.order_id !== undefined && (
                      <span className="review-nmid">
                        <span>Заказ: {review.order_id}</span>
                        <button
                          type="button"
                          className="review-copy-button"
                          onClick={() => void copyValue(String(review.order_id), "order")}
                          aria-label={`Скопировать номер заказа ${review.order_id}`}
                          title="Скопировать номер заказа"
                        >
                          <svg className="review-copy-icon" viewBox="0 0 24 24" aria-hidden="true">
                            <rect x="8" y="8" width="11" height="11" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
                            <path d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4H6.5A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                          </svg>
                        </button>
                        <span className={copiedValue === `order:${review.order_id}` ? "review-copy-success visible" : "review-copy-success"}>Скопировано</span>
                      </span>
                    )}
                  </div>

                  <div className="review-author">
                    <div className="review-avatar">Я</div>
                    <div>
                      <div className="review-buyer">{review.author}</div>
                      <Stars value={review.rating} />
                    </div>
                  </div>

                  {review.comment && <div className="review-text">{review.comment}</div>}

                  {(review.advantages || review.disadvantages) && (
                    <div className="review-pros-cons">
                      {review.advantages && <div className="review-pro"><strong>Плюсы:</strong> {review.advantages}</div>}
                      {review.disadvantages && <div className="review-con"><strong>Минусы:</strong> {review.disadvantages}</div>}
                    </div>
                  )}

                  <div className="review-tags">
                    {review.recommended !== null && <span>{review.recommended ? "Рекомендует товар" : "Не рекомендует товар"}</span>}
                    {review.comments_count > 0 && <span>Комментарии: {review.comments_count}</span>}
                    {review.paid_amount > 0 && <span>Баллы Плюса: {review.paid_amount}</span>}
                    {review.photos.length > 0 && <span>Фото: {review.photos.length}</span>}
                    {review.videos.length > 0 && <span>Видео: {review.videos.length}</span>}
                  </div>

                  {review.photos.length > 0 && (
                    <div className="review-photos">
                      {review.photos.map((url, index) => (
                        <a key={`${review.id}-photo-${index}`} href={url} target="_blank" rel="noreferrer">
                          <img src={url} alt={`Фото отзыва ${index + 1}`} />
                        </a>
                      ))}
                    </div>
                  )}

                  {review.seller_comments?.length > 0 && (
                    <div className="review-answer">
                      <div className="review-answer-label">Ответ продавца</div>
                      {review.seller_comments.map((comment, index) => (
                        <div className="review-answer-text" key={comment.id ?? `${review.id}-seller-${index}`}>
                          {comment.text}
                        </div>
                      ))}
                    </div>
                  )}

                  {review.need_reaction && processingReviewId === review.id && (
                    <div className="review-processing">
                      <div className="review-processing-label">Ответ продавца</div>
                      <textarea
                        value={replyTexts[review.id] || ""}
                        onChange={event => setReplyText(review.id, event.target.value)}
                        placeholder="Здесь в дальнейшем будет предложенный ИИ ответ..."
                        rows={5}
                      />
                      <div className={canSendReply(review.id) ? "review-reply-counter valid" : "review-reply-counter"}>
                        {(replyTexts[review.id] || "").trim().length} / 50 символов
                      </div>
                    </div>
                  )}
                </div>

                <aside className="review-card-right">
                  <div className="review-date">{formatDate(review.created_at)}</div>
                  <div className="review-card-actions">
                    <span className={review.need_reaction ? "review-status-badge unanswered" : "review-status-badge answered"}>
                      {review.need_reaction ? "Без ответа" : (review.is_answered ? "Есть ответ" : "Обработан")}
                    </span>
                    {review.need_reaction && (
                      <>
                        <button type="button" className="review-process-button" onClick={() => toggleProcessing(review.id)}>
                          {processingReviewId === review.id ? "Свернуть" : "Обработать"}
                        </button>
                        <button
                          type="button"
                          className="review-send-button"
                          disabled={!canSendReply(review.id)}
                          title={canSendReply(review.id) ? "Ответить" : "Ответ должен содержать минимум 50 символов"}
                        >
                          Ответить
                        </button>
                      </>
                    )}
                  </div>
                </aside>
              </div>
            </article>
          ))}
        </div>
      )}

      {nextPageToken && (
        <div style={{ display: "flex", justifyContent: "center", marginTop: 20 }}>
          <button type="button" className="reviews-refresh" onClick={() => void loadReviews(status, nextPageToken, true)} disabled={loading}>
            {loading ? "Загрузка..." : "Загрузить ещё"}
          </button>
        </div>
      )}

      {showScrollTop && (
        <button type="button" className="reviews-scroll-top" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })} aria-label="Наверх" title="Наверх">↑</button>
      )}

      {toast && <Toast type={toast.type} message={toast.message} onClose={() => setToast(null)} />}
    </div>
  );
}

export default YandexReviews;
