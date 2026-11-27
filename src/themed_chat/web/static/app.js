import * as api from "./api.js";
import { Transcript } from "./transcript.js";

const byId = (id) => document.getElementById(id);
const start = byId("start");
const login = byId("login");
const chat = byId("chat");
const key = byId("access-key");
const keyError = byId("login-error");
const enter = byId("login-button");
const form = byId("message-form");
const input = byId("message-input");
const send = byId("send-button");
const messageError = byId("message-error");
const chatError = byId("chat-error");
const logoutButton = byId("logout");
const loadEarlier = byId("load-earlier");
const retry = byId("retry");
const transcript = new Transcript({
  scroller: byId("transcript"),
  list: byId("messages"),
  pending: byId("pending"),
  empty: byId("empty"),
  loadEarlier,
});

const MAX_LENGTH = 500;
const REFRESH_INTERVAL_MS = 15000;
const SESSION_EXPIRED = "Сессия истекла. Войдите снова.";
let entering = false;
let sending = false;
let refreshing = false;
// Text of a send that hit an expired session; restored after the next login. Memory only.
let unsentText = "";
// Polling cursor: every turn written after this revision is still to be fetched.
let revision = 0;

function show(section) {
  for (const panel of [start, login, chat]) panel.hidden = panel !== section;
}

// ---- Login ----

function keyProblem(value) {
  if (!/^[A-Za-z0-9_-]*$/.test(value)) {
    return "Ключ может содержать только латинские буквы, цифры, дефис и подчёркивание.";
  }
  if (value.length > 0 && value.length < 8) {
    return `Ключ слишком короткий: нужно не меньше 8 символов, сейчас ${value.length}.`;
  }
  if (value.length > 255) {
    return `Ключ слишком длинный: можно не больше 255 символов, сейчас ${value.length}.`;
  }
  return "";
}

function updateLoginButton() {
  enter.disabled = entering || key.value === "" || keyProblem(key.value) !== "";
}

function onKeyInput() {
  const problem = keyProblem(key.value);
  keyError.textContent = problem;
  key.setAttribute("aria-invalid", String(problem !== ""));
  updateLoginButton();
}

function showLogin(message = "") {
  show(login);
  keyError.textContent = message;
  key.focus();
}

/** Leave the chat (logged out or session lost) and go back to the login screen. */
function endSession(message = "") {
  transcript.clear();
  revision = 0;
  input.value = "";
  chatError.textContent = "";
  updateComposer();
  showLogin(message);
}

// ---- Composer ----

function updateComposer() {
  const size = [...input.value].length; // Code points, like the server counts them.
  const tooLong = size > MAX_LENGTH;
  const blank = /^[\p{White_Space}\u001c-\u001f]*$/u.test(input.value);
  byId("message-count").textContent = `${size} / ${MAX_LENGTH}`;
  byId("message-count").classList.toggle("over", tooLong);
  messageError.textContent = tooLong
    ? `Сообщение длиннее ${MAX_LENGTH} символов: сократите его на ${size - MAX_LENGTH}.`
    : "";
  input.setAttribute("aria-invalid", String(tooLong));
  send.disabled = sending || blank || tooLong;
}

function restoreInput(text) {
  if (input.value === "") input.value = text;
  updateComposer();
}

// ---- Loading history ----

async function loadHistory() {
  retry.hidden = true;
  byId("start-status").textContent = "Загружаем сообщения…";
  show(start);
  try {
    const data = await api.loadMessages();
    byId("title").textContent = data.title;
    document.title = data.title;
    transcript.reset(data.messages, data.has_more);
    revision = data.revision;
    show(chat);
    if (unsentText !== "") restoreInput(unsentText);
    unsentText = "";
    updateComposer();
    input.focus();
  } catch (error) {
    if (error instanceof api.ApiError && error.status === 401) {
      showLogin();
      return;
    }
    byId("start-status").textContent = `Не удалось загрузить историю. ${api.describeError(error)}`;
    retry.hidden = false;
    retry.focus();
  }
}

/** Fetch every turn written after revision `from`, and the cursor after them. */
async function loadChanges(from) {
  const messages = [];
  let after = from;
  for (;;) {
    const data = await api.loadMessages({ after_revision: after, limit: 100 });
    messages.push(...data.messages);
    after = data.revision;
    if (!data.has_more || data.messages.length === 0) return { messages, revision: after };
  }
}

/** Show turns written after `from` and move the cursor past them. */
async function catchUp(from) {
  const changes = await loadChanges(from);
  transcript.append(changes.messages, { follow: true });
  revision = Math.max(revision, changes.revision);
  return changes.messages;
}

/** Pick up messages that other participants wrote. */
async function refreshNew() {
  if (refreshing || sending || chat.hidden) return;
  refreshing = true;
  try {
    const changes = await loadChanges(revision);
    // While a send is in flight it catches up from its own cursor afterwards.
    if (!sending && !chat.hidden) {
      transcript.append(changes.messages);
      revision = Math.max(revision, changes.revision);
    }
  } catch (error) {
    if (error instanceof api.ApiError && error.status === 401) expireSession();
    // Other failures are retried at the next tick.
  } finally {
    refreshing = false;
  }
}

async function showEarlier() {
  loadEarlier.disabled = true;
  chatError.textContent = "";
  try {
    const data = await api.loadMessages({ before: transcript.oldestTurnId });
    transcript.prepend(data.messages, data.has_more);
  } catch (error) {
    if (error instanceof api.ApiError && error.status === 401) expireSession();
    else chatError.textContent = api.describeError(error);
  } finally {
    loadEarlier.disabled = false;
  }
}

// ---- Sending ----

async function submitMessage() {
  if (send.disabled) return;
  const text = input.value;
  const cursor = revision;
  transcript.clearPending();
  const pending = transcript.addPending(text);
  input.value = "";
  sending = true;
  updateComposer();
  chatError.textContent = "";
  byId("chat-status").textContent = "Ассистент готовит ответ…";
  try {
    const data = await api.sendMessage(text);
    pending.remove();
    // Our turn goes in at once; the cursor only moves by polling, so turns that others
    // wrote while we waited still come with the catch-up below or the next refresh.
    transcript.append(data.messages, { follow: true });
    try {
      await catchUp(cursor);
    } catch {
      // The next refresh starts from the same cursor.
    }
  } catch (error) {
    await handleSendFailure(error, text, cursor, pending);
  } finally {
    sending = false;
    byId("chat-status").textContent = "";
    updateComposer();
    if (!chat.hidden) input.focus();
  }
}

/** Keep the sent question and any follow-up draft typed meanwhile (memory only). */
function expireDuringSend(text) {
  const draft = input.value;
  unsentText = draft.trim() !== "" ? `${text}\n\n${draft}` : text;
  expireSession();
}

/** The session ended on its own: keep the unsent text (memory only) for the next login. */
function expireSession() {
  if (unsentText === "" && input.value.trim() !== "") unsentText = input.value;
  endSession(SESSION_EXPIRED);
}

async function handleSendFailure(error, text, cursor, pending) {
  if (error instanceof api.ApiError && error.status === 401) {
    expireDuringSend(text);
    return;
  }
  // A model failure (502/504) is saved as an unanswered turn; after a lost response the
  // turn may be saved too. The server copy, if any, replaces the pending entry.
  let stored = null;
  try {
    const messages = await catchUp(cursor);
    stored = messages.find((m) => m.role === "user" && m.is_mine && m.text === text) ?? null;
  } catch (recoveryError) {
    if (recoveryError instanceof api.ApiError && recoveryError.status === 401) {
      expireDuringSend(text);
      return;
    }
  }
  if (stored?.status === "answered") return; // The reply was lost on the way, not the turn.
  if (stored === null) pending.fail();
  restoreInput(text);
  chatError.textContent = error instanceof api.ApiError
    ? api.describeError(error)
    : "Не удалось отправить сообщение: нет подтверждения от сервера. "
      + "Проверьте соединение и попробуйте ещё раз.";
}

// ---- Events ----

key.addEventListener("input", onKeyInput);
input.addEventListener("input", updateComposer);
retry.addEventListener("click", loadHistory);
loadEarlier.addEventListener("click", showEarlier);
form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitMessage();
});
input.addEventListener("keydown", (event) => {
  // Enter sends, Shift+Enter inserts a newline; Enter that confirms IME composition is ignored.
  if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  form.requestSubmit();
});
byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (enter.disabled) return;
  entering = true;
  updateLoginButton();
  keyError.textContent = "";
  try {
    await api.login(key.value);
  } catch (error) {
    showLogin(api.describeError(error, "login"));
    key.setAttribute("aria-invalid", String(error instanceof api.ApiError && error.status === 401));
    return;
  } finally {
    entering = false;
    updateLoginButton();
  }
  key.value = "";
  key.setAttribute("aria-invalid", "false");
  updateLoginButton();
  await loadHistory();
});
logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    await api.logout();
    unsentText = "";
    endSession();
  } catch (error) {
    chatError.textContent = `Не удалось выйти. ${api.describeError(error)}`;
  } finally {
    logoutButton.disabled = false;
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refreshNew();
});
setInterval(() => {
  if (document.visibilityState === "visible") refreshNew();
}, REFRESH_INTERVAL_MS);

loadHistory();
