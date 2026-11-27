// Thin client for the chat API: one place for requests, error codes and their Russian texts.

/** The server answered with an error status; the request definitely failed. */
export class ApiError extends Error {
  constructor(status, code, retryAfter) {
    super(code ?? `HTTP ${status}`);
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

/** No usable answer arrived (offline, reset connection, unreadable body): the outcome is unknown. */
export class NetworkError extends Error {}

async function errorFrom(response) {
  const body = await response.json().catch(() => null);
  const retryAfter = Number.parseInt(response.headers.get("Retry-After") ?? "", 10);
  return new ApiError(
    response.status,
    typeof body?.error?.code === "string" ? body.error.code : null,
    Number.isFinite(retryAfter) ? retryAfter : null,
  );
}

async function request(method, path, { headers = {}, json } = {}) {
  const init = { method, headers: { ...headers }, cache: "no-store" };
  if (json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new NetworkError("fetch failed");
  }
  if (!response.ok) throw await errorFrom(response);
  if (response.status === 204) return null;
  try {
    return await response.json();
  } catch {
    throw new NetworkError("unreadable response body");
  }
}

// The access key travels once, in a header, and is never stored.
export const login = (accessKey) =>
  request("POST", "./api/session", { headers: { "X-Access-Key": accessKey } });
export const logout = () => request("DELETE", "./api/session");

/** Query: { limit, before, after } (turn ids are the cursors). */
export function loadMessages(query = {}) {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) params.set(name, String(value));
  }
  const suffix = params.size > 0 ? `?${params}` : "";
  return request("GET", `./api/messages${suffix}`);
}
export const sendMessage = (text) => request("POST", "./api/messages", { json: { text } });

const wait = (error) => (error.retryAfter ? `${error.retryAfter} с` : "несколько секунд");

/** A clear Russian text for any failed request; `what` names the rate-limited action. */
export function describeError(error, what = "message") {
  if (error instanceof NetworkError) return "Нет связи с сервером. Проверьте соединение.";
  if (!(error instanceof ApiError)) return "Что-то пошло не так. Попробуйте ещё раз.";
  switch (true) {
    case error.status === 401:
      return what === "login" ? "Неверный ключ доступа." : "Сессия истекла. Войдите снова.";
    case error.status === 403 && error.code === "origin_not_allowed":
      return "Запрос отклонён: адрес страницы не совпадает с адресом, настроенным на сервере. "
        + "Откройте чат по адресу, который указал администратор.";
    case error.status === 422:
      return what === "login"
        ? "Проверьте ключ доступа."
        : "Проверьте текст сообщения: от 1 до 500 символов, не только пробелы.";
    case error.status === 429:
      return what === "login"
        ? `Слишком много попыток, подождите ${wait(error)}.`
        : `Слишком много сообщений, подождите ${wait(error)}.`;
    case error.status === 502:
      return "Не удалось получить ответ. Попробуйте ещё раз.";
    case error.status === 503:
      return "Сервис временно недоступен. Попробуйте позже.";
    case error.status === 504:
      return "Ассистент не успел ответить. Попробуйте ещё раз.";
    case error.status >= 500:
      return "Сервер недоступен, попробуйте позже.";
    default:
      return "Не удалось выполнить запрос. Попробуйте ещё раз.";
  }
}
