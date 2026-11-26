const byId = (id) => document.getElementById(id);
const start = byId("start");
const login = byId("login");
const chat = byId("chat");
const key = byId("access-key");
const enter = byId("login-button");
const input = byId("message-input");
const send = byId("send-button");
const history = byId("messages");
const retry = byId("retry");
const recovery = byId("recovery");
const refreshHistory = byId("refresh-history");
const allowNewSend = byId("allow-new-send");
const maximum = 500;
const keyPattern = /^[A-Za-z0-9_-]{8,255}$/;
const dateFormat = new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" });
let entering = false;
let sending = false;
let uncertainText = null;
let historyChecked = false;

function show(section) {
  for (const panel of [start, login, chat]) panel.hidden = panel !== section;
}

function updateLogin() {
  enter.disabled = entering || !keyPattern.test(key.value);
}

function updateComposer() {
  const size = [...input.value].length;
  byId("message-count").textContent = `${size} / ${maximum}`;
  byId("message-count").classList.toggle("over", size > maximum);
  const blank = /^[\p{White_Space}\u001c-\u001f]*$/u.test(input.value);
  send.disabled = sending || blank || size > maximum || (
    uncertainText !== null && (!historyChecked || input.value === uncertainText)
  );
}

function appendMessages(messages) {
  for (const message of messages) {
    const item = document.createElement("li");
    item.className = message.is_mine ? "message mine" : "message";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const author = document.createElement("strong");
    author.textContent = message.role === "assistant" ? "Ассистент" : message.is_mine ? "Вы" : "Гость";
    const time = document.createElement("time");
    time.dateTime = message.created_at;
    time.textContent = dateFormat.format(new Date(message.created_at));
    meta.append(author, time);
    const body = document.createElement("p");
    body.className = "message-body";
    body.textContent = message.text;
    item.append(meta, body);
    history.append(item);
  }
  byId("empty").hidden = history.children.length !== 0;
}

function showLogin(message = "") {
  show(login);
  byId("login-error").textContent = message;
  key.focus();
}

function scrollToLatest() {
  const transcript = byId("transcript");
  transcript.scrollTop = transcript.scrollHeight;
}

async function loadHistory() {
  retry.hidden = true;
  byId("start-status").textContent = "Загружаем сообщения…";
  show(start);
  try {
    const response = await fetch("./api/messages", { cache: "no-store" });
    if (response.status === 401) {
      showLogin();
      return;
    }
    if (!response.ok) throw new Error("Unable to load chat");
    const data = await response.json();
    byId("title").textContent = data.title;
    document.title = data.title;
    history.replaceChildren();
    appendMessages(data.messages);
    show(chat);
    if (uncertainText !== null) {
      historyChecked = true;
      allowNewSend.hidden = false;
      byId("chat-error").textContent = "История обновлена. Проверьте, появился ли ваш вопрос.";
    }
    updateComposer();
    scrollToLatest();
    input.focus();
  } catch {
    byId("start-status").textContent = "Не удалось загрузить историю.";
    retry.hidden = false;
    retry.focus();
  }
}

key.addEventListener("input", updateLogin);
input.addEventListener("input", updateComposer);
retry.addEventListener("click", loadHistory);
refreshHistory.addEventListener("click", loadHistory);
allowNewSend.addEventListener("click", () => {
  uncertainText = null;
  recovery.hidden = true;
  byId("chat-error").textContent = "";
  updateComposer();
  input.focus();
});
byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (enter.disabled) return;
  entering = true;
  updateLogin();
  byId("login-error").textContent = "";
  try {
    const response = await fetch("./api/session", {
      method: "POST", headers: { "X-Access-Key": key.value },
    });
    if (response.status === 401) {
      showLogin("Неверный ключ доступа.");
      return;
    }
    if (!response.ok) throw new Error("Unable to start session");
    key.value = "";
    await loadHistory();
  } catch {
    showLogin("Не удалось войти. Попробуйте ещё раз.");
  } finally {
    entering = false;
    updateLogin();
  }
});

byId("message-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (send.disabled) return;
  const text = input.value;
  uncertainText = null;
  recovery.hidden = true;
  sending = true;
  updateComposer();
  byId("chat-error").textContent = "";
  byId("chat-status").textContent = "Ассистент готовит ответ…";
  try {
    const response = await fetch("./api/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (response.status === 401) {
      showLogin("Сессия истекла. Войдите снова.");
      return;
    }
    if (!response.ok) {
      const failure = await response.json().catch(() => null);
      if (response.status === 504 && failure?.detail === "model_timeout") {
        byId("chat-error").textContent = "Ассистент не успел ответить. Попробуйте ещё раз.";
        return;
      }
      if (response.status === 502 && failure?.detail === "model_unavailable") {
        byId("chat-error").textContent = "Не удалось получить ответ. Попробуйте ещё раз.";
        return;
      }
      if (response.status === 422) {
        byId("chat-error").textContent = "Проверьте текст сообщения.";
        return;
      }
      throw new Error("Unable to confirm message delivery");
    }
    const data = await response.json();
    appendMessages(data.messages);
    if (input.value === text) input.value = "";
    scrollToLatest();
    input.focus();
  } catch {
    uncertainText = text;
    historyChecked = false;
    allowNewSend.hidden = true;
    recovery.hidden = false;
    byId("chat-error").textContent = "Не удалось подтвердить отправку. Сначала сверьтесь с историей.";
    if (document.activeElement === document.body) refreshHistory.focus();
  } finally {
    sending = false;
    byId("chat-status").textContent = "";
    updateComposer();
    if (!chat.hidden && document.activeElement === document.body) input.focus();
  }
});

loadHistory();
