import { useEffect, useRef, useState } from "react";
import Loader from "./components/Loader";
import Toast, { type ToastType } from "./components/Toast";
import "./Reviews.css";
import DateFilter from "./DateFilter";

type Status = "unanswered" | "rating_only" | "answered" | "all";

interface Review {
  id: string;
  text: string;
  pros: string;
  cons: string;
  rating: number | null;
  created_at: string | null;
  buyer_name: string;
  is_answered: boolean;
  answer: {
    text: string;
    editable: boolean;
  } | null;
  article?: string;
  nm_id?: number;
  product_name?: string;
  color?: string;
  photo_links: {
    fullSize?: string;
    miniSize?: string;
  }[];
  was_viewed: boolean;
  bables: string[];
}

interface ResponseData {
  status: string;
  count_unanswered: number | null;
  count_archive: number | null;
  count_filtered: number;
  reviews: Review[];
}

interface ToastState {
  message: string;
  type: ToastType;
}

type SelectOption<T extends string> = {
  value: T;
  label: string;
};

function CustomSelect<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: T;
  options: SelectOption<T>[];
  onChange: (value: T) => void;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const selected = options.find(option => option.value === value) || options[0];

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={ref} className={`reviews-custom-select${open ? " is-open" : ""}`}>
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

function formatDate(value: string | null): string {
  if (!value) {
    return "Дата не указана";
  }

  // WB отдаёт created_at в UTC. В БД это поле хранится без timezone,
  // поэтому явно трактуем ISO-значение без offset как UTC, а отображаем
  // пользователю в московском времени.
  const normalized = /(?:Z|[+-]\\d{2}:?\\d{2})$/.test(value)
    ? value
    : value.replace(" ", "T") + "Z";

  const date = new Date(normalized);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function Stars({
  value
}: {
  value: number | null;
}) {
  if (!value) {
    return (
      <span className="review-rating-empty">
        Без оценки
      </span>
    );
  }

  return (
    <span className="review-stars">
      {"★".repeat(value)}
      <span className="review-stars-muted">
        {"★".repeat(Math.max(0, 5 - value))}
      </span>
    </span>
  );
}

function Reviews() {
  const [status, setStatus] =
    useState<Status>("unanswered");

  const [reviews, setReviews] =
    useState<Review[]>([]);

  const [unanswered, setUnanswered] =
    useState<number | null>(null);

  const [countFiltered, setCountFiltered] =
    useState(0);

  const [page, setPage] =
    useState(0);

  const [filters, setFilters] =
    useState({
      dateFrom: "",
      dateTo: "",
      rating: "",
      article: ""
    });

  const [appliedFilters, setAppliedFilters] =
    useState({
      dateFrom: "",
      dateTo: "",
      rating: "",
      article: ""
    });

  const [loading, setLoading] =
    useState(false);

  const [showScrollTop, setShowScrollTop] =
    useState(false);

  const [toast, setToast] =
    useState<ToastState | null>(null);

  const [copiedNmId, setCopiedNmId] =
    useState<number | null>(null);

  const [processingReviewId, setProcessingReviewId] =
    useState<string | null>(null);

  const [replyTexts, setReplyTexts] =
    useState<Record<string, string>>({});

  const copyNmId = async (nmId: number) => {
    try {
      await navigator.clipboard.writeText(
        String(nmId)
      );

      setCopiedNmId(nmId);

      window.setTimeout(() => {
        setCopiedNmId(current =>
          current === nmId ? null : current
        );
      }, 2500);
    } catch {
      setToast({
        type: "error",
        message: "Не удалось скопировать nmID"
      });
    }
  };

  const toggleProcessing = (
    reviewId: string
  ) => {
    setProcessingReviewId(current =>
      current === reviewId ? null : reviewId
    );
  };

  const setReplyText = (
    reviewId: string,
    value: string
  ) => {
    setReplyTexts(current => ({
      ...current,
      [reviewId]: value
    }));
  };

  const canSendReply = (
    reviewId: string
  ): boolean => {
    return (
      replyTexts[reviewId] || ""
    ).trim().length >= 50;
  };

  const loadReviews = async (
    nextStatus: Status = status,
    nextPage: number = page,
    nextFilters = appliedFilters
  ) => {
    setLoading(true);

    try {
      const params = new URLSearchParams({
        status: nextStatus,
        take: "100",
        skip: String(nextPage * 100),
        order: "dateDesc"
      });

      if (nextFilters.dateFrom) {
        params.set("date_from", nextFilters.dateFrom);
      }

      if (nextFilters.dateTo) {
        params.set("date_to", nextFilters.dateTo);
      }

      if (nextFilters.rating) {
        params.set("rating", nextFilters.rating);
      }

      if (nextFilters.article.trim()) {
        params.set("article", nextFilters.article.trim());
      }

      const response = await fetch(
        `http://127.0.0.1:8000/wb/reviews?${params.toString()}`
      );

      if (!response.ok) {
        let message =
          `Ошибка сервера: ${response.status}`;

        try {
          const errorData =
            await response.json();

          if (errorData.detail) {
            message = String(errorData.detail);
          }
        } catch {
          // Используем HTTP status.
        }

        throw new Error(message);
      }

      const data =
        await response.json() as ResponseData;

      if (data.status !== "ok") {
        throw new Error(
          "WB не вернул отзывы"
        );
      }

      setReviews(data.reviews || []);
      setUnanswered(data.count_unanswered);
      setCountFiltered(Number(data.count_filtered) || 0);
    } catch (error) {
      setToast({
        type: "error",
        message:
          error instanceof Error
            ? error.message
            : "Не удалось загрузить отзывы WB"
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {

    const handleWindowScroll = () => {
      setShowScrollTop(window.scrollY > 300);
    };

    handleWindowScroll();

    window.addEventListener(
      "scroll",
      handleWindowScroll,
      { passive: true }
    );

    return () => {
      window.removeEventListener(
        "scroll",
        handleWindowScroll
      );
    };

  }, []);

  useEffect(() => {
    void loadReviews("unanswered", 0, {
      dateFrom: "",
      dateTo: "",
      rating: "",
      article: ""
    });
  }, []);

  const scrollPageToTop = () => {

    window.scrollTo({
      top: 0,
      behavior: "smooth"
    });

  };


  return (
    <div className="reviews-page">

      <div className="reviews-header">
        <div>
          <h1>Отзывы и вопросы</h1>

          <p>
            Отзывы покупателей Wildberries.
            Сейчас только получение данных.
          </p>
        </div>
      </div>


      <div className="reviews-toolbar">

        <div className="reviews-tabs">

          {(
            [
              ["unanswered", "Без ответа"],
              ["rating_only", "Только оценка"],
              ["answered", "С ответом"],
              ["all", "Все отзывы"]
            ] as const
          ).map(([value, label]) => (

            <button
              type="button"
              key={value}
              className={
                status === value
                  ? "reviews-tab active"
                  : "reviews-tab"
              }
              onClick={() => {
                setStatus(value);
                setPage(0);
                void loadReviews(value, 0, appliedFilters);
              }}
            >

              <span>
                {label}
              </span>

              {value === "unanswered" &&
                unanswered !== null && (

                <span className="reviews-tab-count">
                  {unanswered}
                </span>

              )}

            </button>

          ))}

        </div>

        <div className="reviews-result-count">
          {countFiltered} отзывов
        </div>

        <button
          type="button"
          className="reviews-refresh"
          onClick={() => void loadReviews(status, page, appliedFilters)}
          disabled={loading}
        >

          {loading ? (
            <>
              <Loader size="small" />
              Загрузка...
            </>
          ) : (
            "Обновить"
          )}

        </button>

      </div>

      <div className="reviews-filters">
        <label className="reviews-filter-field reviews-filter-date">
          <span>Дата от</span>
          <DateFilter
            value={filters.dateFrom}
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
            onChange={event =>
              setFilters(current => ({ ...current, article: event.target.value }))
            }
            placeholder="Введите артикул"
          />
        </label>

        <div className="reviews-filter-actions">
          <button
            type="button"
            className="reviews-filter-apply"
            onClick={() => {
              setAppliedFilters(filters);
              setPage(0);
              void loadReviews(status, 0, filters);
            }}
            disabled={loading}
          >
            Применить
          </button>
          <button
            type="button"
            className="reviews-filter-reset"
            onClick={() => {
              const emptyFilters = {
                dateFrom: "",
                dateTo: "",
                rating: "",
                article: ""
              };
              setFilters(emptyFilters);
              setAppliedFilters(emptyFilters);
              setPage(0);
              void loadReviews(status, 0, emptyFilters);
            }}
            disabled={loading}
          >
            Сбросить
          </button>
        </div>
      </div>

      {loading && reviews.length === 0 ? (

        <div className="reviews-loading">
          <Loader size="small" />
          <span>Получаем отзывы WB...</span>
        </div>

      ) : reviews.length === 0 ? (

        <div className="reviews-empty">
          Отзывов по выбранному фильтру нет.
        </div>

      ) : (

        <>
          <div className="reviews-list">

          {reviews.map(review => (

            <article
              className="review-card"
              key={review.id}
            >
              <div className="review-card-columns">

                <div className="review-card-left">

                  <div className="review-product-name">
                    {review.product_name || "Товар без названия"}
                  </div>

                  <div className="review-product-meta">
                    <span>{review.article || "Без артикула"}</span>

                    {review.nm_id && (
                      <span className="review-nmid">
                        <span className="review-nmid-separator">WB:</span>
                        <span>{review.nm_id}</span>

                        <button
                          type="button"
                          className="review-copy-button"
                          onClick={() => void copyNmId(review.nm_id!)}
                          aria-label={`Скопировать ${review.nm_id}`}
                          title="Скопировать"
                        >
                          <svg
                            className="review-copy-icon"
                            viewBox="0 0 24 24"
                            aria-hidden="true"
                          >
                            <rect
                              x="8"
                              y="8"
                              width="11"
                              height="11"
                              rx="2"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.8"
                            />
                            <path
                              d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4H6.5A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.8"
                              strokeLinecap="round"
                            />
                          </svg>
                        </button>

                        <span
                          className={
                            copiedNmId === review.nm_id
                              ? "review-copy-success visible"
                              : "review-copy-success"
                          }
                          aria-hidden={copiedNmId !== review.nm_id}
                        >
                          Скопировано
                        </span>
                      </span>
                    )}
                  </div>

                  <div className="review-author">
                    <div className="review-avatar">
                      {(review.buyer_name || "П").slice(0, 1).toUpperCase()}
                    </div>

                    <div>
                      <div className="review-buyer">
                        {review.buyer_name || "Покупатель"}
                      </div>
                      <Stars value={review.rating} />
                    </div>
                  </div>

                  {review.text && (
                    <div className="review-text">
                      {review.text}
                    </div>
                  )}

                  {(review.pros || review.cons) && (
                    <div className="review-pros-cons">
                      {review.pros && (
                        <div className="review-pro">
                          <strong>Плюсы:</strong>
                          {review.pros}
                        </div>
                      )}

                      {review.cons && (
                        <div className="review-con">
                          <strong>Минусы:</strong>
                          {review.cons}
                        </div>
                      )}
                    </div>
                  )}

                  {review.bables.length > 0 && (
                    <div className="review-tags">
                      {review.bables.map(tag => (
                        <span key={tag}>{tag}</span>
                      ))}
                    </div>
                  )}

                  {review.photo_links.length > 0 && (
                    <div className="review-photos">
                      {review.photo_links.map((photo, index) => {
                        const src = photo.miniSize || photo.fullSize;

                        if (!src) {
                          return null;
                        }

                        return (
                          <a
                            href={photo.fullSize || src}
                            target="_blank"
                            rel="noreferrer"
                            key={`${review.id}-${index}`}
                          >
                            <img src={src} alt="Фото из отзыва" />
                          </a>
                        );
                      })}
                    </div>
                  )}

                  {review.answer && (
                    <div className="review-answer">
                      <div className="review-answer-label">
                        Ответ продавца
                      </div>
                      <div className="review-answer-text">
                        {review.answer.text}
                      </div>
                    </div>
                  )}

                  {processingReviewId === review.id && (
                    <div className="review-processing">
                      <div className="review-processing-label">
                        Ответ продавца
                      </div>

                      <textarea
                        value={replyTexts[review.id] || ""}
                        onChange={event =>
                          setReplyText(review.id, event.target.value)
                        }
                        placeholder="Здесь в дальнейшем будет предложенный ИИ ответ..."
                        rows={5}
                      />

                      <div
                        className={
                          (replyTexts[review.id] || "").trim().length >= 50
                            ? "review-reply-counter valid"
                            : "review-reply-counter"
                        }
                      >
                        {(replyTexts[review.id] || "").trim().length} / 50 символов
                      </div>
                    </div>
                  )}

                </div>

                <aside className="review-card-right">

                  <div className="review-date">
                    {formatDate(review.created_at)}
                  </div>

                  <div className="review-card-actions">

                    <span
                      className={
                        review.is_answered
                          ? "review-status-badge answered"
                          : "review-status-badge unanswered"
                      }
                    >
                      {review.is_answered ? "Есть ответ" : "Без ответа"}
                    </span>

                    {!review.is_answered && (
                      <>
                        <button
                          type="button"
                          className="review-process-button"
                          onClick={() => toggleProcessing(review.id)}
                        >
                          {processingReviewId === review.id
                            ? "Свернуть"
                            : "Обработать"}
                        </button>

                        <button
                          type="button"
                          className="review-send-button"
                          disabled={!canSendReply(review.id)}
                          title={
                            canSendReply(review.id)
                              ? "Ответить"
                              : "Ответ должен содержать минимум 50 символов"
                          }
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

        {countFiltered > 0 && (
          <div className="reviews-pagination">
            <div className="reviews-pagination-info">
              {page * 100 + 1}–{Math.min((page + 1) * 100, countFiltered)} из {countFiltered}
            </div>
            <div className="reviews-pagination-buttons">
              <button
                type="button"
                className="reviews-page-button"
                onClick={() => {
                  const nextPage = page - 1;
                  setPage(nextPage);
                  void loadReviews(status, nextPage, appliedFilters);
                }}
                disabled={page === 0 || loading}
              >
                Назад
              </button>
              <span className="reviews-page-number">
                Страница {page + 1} из {Math.max(1, Math.ceil(countFiltered / 100))}
              </span>
              <button
                type="button"
                className="reviews-page-button"
                onClick={() => {
                  const nextPage = page + 1;
                  setPage(nextPage);
                  void loadReviews(status, nextPage, appliedFilters);
                }}
                disabled={(page + 1) * 100 >= countFiltered || loading}
              >
                Далее
              </button>
            </div>
          </div>
        )}
        </>

      )}


      {showScrollTop && (

        <button
          type="button"
          className="reviews-scroll-top"
          onClick={scrollPageToTop}
          aria-label="Наверх"
          title="Наверх"
        >
          ↑
        </button>

      )}


      {toast && (

        <Toast
          type={toast.type}
          message={toast.message}
          onClose={() => setToast(null)}
        />

      )}

    </div>
  );
}

export default Reviews;
