import { useEffect, useState } from "react";
import Loader from "./components/Loader";
import Toast, { type ToastType } from "./components/Toast";
import "./Reviews.css";
import DateFilter from "./DateFilter";

type Status = "unanswered" | "answered" | "all";

interface QuestionFilters {
  dateFrom: string;
  dateTo: string;
  article: string;
}

interface YandexAnswerComment {
  id: number | null;
  text: string;
  author: string;
  author_type?: string | null;
  status?: string | null;
  can_modify?: boolean;
  parent_id?: number | null;
}

interface YandexAnswer {
  id: number | null;
  text: string;
  author: string;
  author_type?: string | null;
  status?: string | null;
  created_at: string | null;
  can_modify?: boolean;
  comments: YandexAnswerComment[];
}

interface YandexQuestion {
  id: string;
  created_at: string | null;
  author: string;
  author_type?: string | null;
  offer_id?: string | null;
  product_name?: string | null;
  category_id?: number | null;
  text: string;
  likes: number;
  dislikes: number;
  need_answer: boolean;
  answers: YandexAnswer[];
  seller_answers: YandexAnswer[];
}

interface ResponseData {
  status: string;
  message?: string;
  business_id?: number;
  questions: YandexQuestion[];
  total_count?: number | null;
  next_page_token?: string | null;
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

function YandexQuestions() {
  const [status, setStatus] = useState<Status>("unanswered");
  const [questions, setQuestions] = useState<YandexQuestion[]>([]);
  const [filters, setFilters] = useState<QuestionFilters>({ dateFrom: "", dateTo: "", article: "" });
  const [appliedFilters, setAppliedFilters] = useState<QuestionFilters>({ dateFrom: "", dateTo: "", article: "" });
  const [countFiltered, setCountFiltered] = useState(0);
  const [unanswered, setUnanswered] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [businessId, setBusinessId] = useState<number | null>(null);
  const [processingQuestionId, setProcessingQuestionId] = useState<string | null>(null);
  const [replyTexts, setReplyTexts] = useState<Record<string, string>>({});
  const [showScrollTop, setShowScrollTop] = useState(false);
  const [toast, setToast] = useState<{ type: ToastType; message: string } | null>(null);
  const [copiedValue, setCopiedValue] = useState<string | null>(null);

  const loadCount = async () => {
    try {
      const response = await fetch("http://127.0.0.1:8000/yandex/questions/count");
      if (!response.ok) return;
      const data = await response.json();
      const count = Number(data.count_unanswered);
      if (data.status === "ok" && Number.isFinite(count) && count >= 0) {
        setUnanswered(count);
      }
    } catch {
      // Счётчик не должен ломать загрузку вопросов.
    }
  };

  const loadQuestions = async (
    nextStatus: Status = status,
    pageToken: string | null = null,
    append = false,
    nextFilters: QuestionFilters = appliedFilters
  ) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ status: nextStatus, limit: "50" });
      if (pageToken) params.set("page_token", pageToken);
      if (nextFilters.dateFrom) params.set("date_from", nextFilters.dateFrom);
      if (nextFilters.dateTo) params.set("date_to", nextFilters.dateTo);
      if (nextFilters.article.trim()) params.set("article", nextFilters.article.trim());
      const response = await fetch(`http://127.0.0.1:8000/yandex/questions?${params.toString()}`);
      const data = await response.json() as ResponseData;
      if (!response.ok || data.status !== "ok") {
        throw new Error(data.message || `Ошибка сервера: ${response.status}`);
      }
      setQuestions(current => append ? [...current, ...(data.questions || [])] : (data.questions || []));
      setNextPageToken(data.next_page_token || null);
      setBusinessId(data.business_id || null);
      setCountFiltered(Number(data.total_count) || 0);
      if (data.total_count !== null && data.total_count !== undefined && nextStatus === "unanswered") {
        setUnanswered(Number(data.total_count));
      }
    } catch (error) {
      setToast({
        type: "error",
        message: error instanceof Error ? error.message : "Не удалось загрузить вопросы Яндекс Маркета"
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

  const toggleProcessing = (questionId: string) => {
    setProcessingQuestionId(current => current === questionId ? null : questionId);
  };

  const setReplyText = (questionId: string, value: string) => {
    setReplyTexts(current => ({ ...current, [questionId]: value }));
  };

  const canSendReply = (questionId: string) =>
    (replyTexts[questionId] || "").trim().length >= 1;

  const refresh = async () => {
    await Promise.all([loadQuestions(status, null, false, appliedFilters), loadCount()]);
  };

  useEffect(() => {
    void Promise.all([loadQuestions("unanswered", null, false, { dateFrom: "", dateTo: "", article: "" }), loadCount()]);
  }, []);

  useEffect(() => {
    const onScroll = () => setShowScrollTop(window.scrollY > 300);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const changeStatus = (value: Status) => {
    setStatus(value);
    setNextPageToken(null);
    setProcessingQuestionId(null);
    void loadQuestions(value, null, false, appliedFilters);
  };

  return (
    <div className="reviews-page">
      <div className="reviews-header">
        <div>
          <h1>Отзывы и вопросы</h1>
          <p>Вопросы покупателей Яндекс Маркета.{businessId ? ` Кабинет: ${businessId}.` : ""}</p>
        </div>
      </div>

      <div className="reviews-toolbar">
        <div className="reviews-tabs">
          {([["unanswered", "Без ответа"], ["answered", "С ответом"], ["all", "Все"]] as const).map(([value, label]) => (
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
        <div className="reviews-result-count">Найдено: {countFiltered}</div>
        <button type="button" className="reviews-refresh" onClick={() => void refresh()} disabled={loading}>
          {loading ? <><Loader size="small" />Загрузка...</> : "Обновить"}
        </button>
      </div>

      <div className="reviews-filters questions-filters">
        <label className="reviews-filter-field reviews-filter-date">
          <span>Дата от</span>
          <DateFilter value={filters.dateFrom} onChange={value => setFilters(current => ({ ...current, dateFrom: value }))} />
        </label>
        <label className="reviews-filter-field reviews-filter-date">
          <span>Дата до</span>
          <DateFilter value={filters.dateTo} onChange={value => setFilters(current => ({ ...current, dateTo: value }))} />
        </label>
        <label className="reviews-filter-field reviews-filter-article">
          <span>Артикул продавца</span>
          <input type="text" value={filters.article} onChange={event => setFilters(current => ({ ...current, article: event.target.value }))} placeholder="Введите артикул" />
        </label>
        <div className="reviews-filter-actions">
          <button type="button" className="reviews-filter-apply" onClick={() => { setAppliedFilters(filters); setNextPageToken(null); void loadQuestions(status, null, false, filters); }} disabled={loading}>Применить</button>
          <button type="button" className="reviews-filter-reset" onClick={() => { const empty = { dateFrom: "", dateTo: "", article: "" }; setFilters(empty); setAppliedFilters(empty); setNextPageToken(null); void loadQuestions(status, null, false, empty); }} disabled={loading}>Сбросить</button>
        </div>
      </div>

      {loading && questions.length === 0 ? (
        <div className="reviews-loading"><Loader size="small" /><span>Получаем вопросы Яндекс Маркета...</span></div>
      ) : questions.length === 0 ? (
        <div className="reviews-empty">Вопросов по выбранному фильтру нет.</div>
      ) : (
        <div className="reviews-list">
          {questions.map(question => (
            <article className="review-card" key={question.id}>
              <div className="review-card-columns">
                <div className="review-card-left">
                  <div className="review-product-name">
                    {question.product_name || question.offer_id || "Товар Яндекс Маркета"}
                  </div>

                  <div className="review-product-meta">
                    <span>Артикул: {question.offer_id || "Без артикула"}</span>
                    {question.offer_id && (
                      <span className="review-nmid">
                        {/* <button
                          type="button"
                          className="review-copy-button"
                          onClick={() => void copyValue(question.offer_id!, "article")}
                          aria-label={`Скопировать артикул ${question.offer_id}`}
                          title="Скопировать артикул"
                        >
                          <svg className="review-copy-icon" viewBox="0 0 24 24" aria-hidden="true">
                            <rect x="8" y="8" width="11" height="11" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
                            <path d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4H6.5A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                          </svg>
                        </button> */}
                        <span className={copiedValue === `article:${question.offer_id}` ? "review-copy-success visible" : "review-copy-success"}>Скопировано</span>
                      </span>
                    )}

                    <span className="review-nmid">
                      <span>Вопрос №{question.id}</span>
                      <button
                        type="button"
                        className="review-copy-button"
                        onClick={() => void copyValue(String(question.id), "question")}
                        aria-label={`Скопировать номер вопроса ${question.id}`}
                        title="Скопировать номер вопроса"
                      >
                        <svg className="review-copy-icon" viewBox="0 0 24 24" aria-hidden="true">
                          <rect x="8" y="8" width="11" height="11" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
                          <path d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4H6.5A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                        </svg>
                      </button>
                      <span className={copiedValue === `question:${question.id}` ? "review-copy-success visible" : "review-copy-success"}>Скопировано</span>
                    </span>
                  </div>

                  <div className="review-author">
                    <div className="review-avatar">Я</div>
                    <div>
                      <div className="review-buyer">{question.author}</div>
                      <div className="review-rating-empty">Вопрос о товаре</div>
                    </div>
                  </div>

                  <div className="review-text">{question.text || "Вопрос без текста"}</div>

                  {(question.likes > 0 || question.dislikes > 0) && (
                    <div className="review-tags">
                      <span>Нравится: {question.likes}</span>
                      <span>Не нравится: {question.dislikes}</span>
                    </div>
                  )}

                  {question.seller_answers?.length > 0 && (
                    <div className="review-answer">
                      <div className="review-answer-label">Ответ продавца</div>
                      {question.seller_answers.map((answer, index) => (
                        <div className="review-answer-text" key={answer.id ?? `${question.id}-seller-${index}`}>
                          {answer.text}
                        </div>
                      ))}
                    </div>
                  )}

                  {question.need_answer && processingQuestionId === question.id && (
                    <div className="review-processing">
                      <div className="review-processing-label">Ответ продавца</div>
                      <textarea
                        value={replyTexts[question.id] || ""}
                        onChange={event => setReplyText(question.id, event.target.value)}
                        placeholder="Здесь в дальнейшем будет предложенный ИИ ответ..."
                        rows={5}
                      />
                      <div className="review-reply-counter">
                        {(replyTexts[question.id] || "").trim().length} символов
                      </div>
                    </div>
                  )}
                </div>

                <aside className="review-card-right">
                  <div className="review-date">{formatDate(question.created_at)}</div>
                  <div className="review-card-actions">
                    <span className={question.need_answer ? "review-status-badge unanswered" : "review-status-badge answered"}>
                      {question.need_answer ? "Нужен ответ" : "Вопрос получен"}
                    </span>
                    {question.need_answer && (
                      <>
                        <button type="button" className="review-process-button" onClick={() => toggleProcessing(question.id)}>
                          {processingQuestionId === question.id ? "Свернуть" : "Обработать"}
                        </button>
                        <button
                          type="button"
                          className="review-send-button"
                          disabled={!canSendReply(question.id)}
                          title={canSendReply(question.id) ? "Ответить" : "Введите ответ"}
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
          <button type="button" className="reviews-refresh" onClick={() => void loadQuestions(status, nextPageToken, true, appliedFilters)} disabled={loading}>
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

export default YandexQuestions;
