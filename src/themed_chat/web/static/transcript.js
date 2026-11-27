// The message list: rendering, turn cursors, scroll behaviour and pending (unsent) messages.
import { renderMarkdown } from "./markdown.js";

const dateFormat = new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" });
const NEAR_BOTTOM_PX = 48;

function element(name, className, text) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function item(className, authorName, stamp, body) {
  const entry = element("li", className);
  const meta = element("div", "message-meta");
  meta.append(element("strong", undefined, authorName), stamp);
  entry.append(meta, body);
  return entry;
}

function messageItem(message) {
  const assistant = message.role === "assistant";
  const stamp = element("time", undefined, dateFormat.format(new Date(message.created_at)));
  stamp.dateTime = message.created_at;
  let body;
  if (assistant) {
    body = element("div", "message-body markdown");
    body.append(renderMarkdown(message.text));
  } else {
    body = element("p", "message-body", message.text);
  }
  const name = assistant ? "Ассистент" : message.is_mine ? "Вы" : "Гость";
  const failed = !assistant && message.status === "failed";
  const classes = ["message", message.is_mine ? "mine" : "", failed ? "failed" : ""];
  const entry = item(classes.filter(Boolean).join(" "), name, stamp, body);
  if (failed) entry.querySelector(".message-meta").append(element("span", "pending-status", "Ответ не получен"));
  entry.dataset.turnId = String(message.turn_id);
  entry.dataset.messageId = message.id;
  return entry;
}

/**
 * Display order: (question_at, turn id), and a turn's question before its answer.
 * The API sends question_at as fixed-width UTC with microseconds, so comparing the strings
 * compares the times at the server's precision (Date would round to milliseconds).
 */
function sortKey(message) {
  return [message.question_at, message.turn_id, message.role === "user" ? 0 : 1];
}

function before(a, b) {
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] !== b[index]) return a[index] < b[index];
  }
  return false;
}

export class Transcript {
  constructor({ scroller, list, pending, empty, loadEarlier }) {
    this.scroller = scroller;
    this.list = list;
    this.pending = pending;
    this.empty = empty;
    this.loadEarlier = loadEarlier;
    this.clear();
  }

  clear() {
    this.list.replaceChildren();
    this.pending.replaceChildren();
    this.seen = new Set();
    this.keys = new WeakMap();
    this.waiting = new Set();
    this.hasMore = false;
    // The oldest turn of the pages loaded from the history ("show earlier" continues there).
    // Polled turns can sort above it but do not move it, so paging leaves no gaps.
    this.pageStart = null;
    this.#update();
  }

  /** Replace everything with the latest page and show its end. */
  reset(messages, hasMore) {
    this.clear();
    this.hasMore = hasMore;
    this.pageStart = messages.length > 0 ? messages[0].turn_id : null;
    this.#insert(messages);
    this.#update();
    this.scrollToLatest();
  }

  /** Add newer turns; the view only follows when the reader is already at the end. */
  append(messages, { follow = false } = {}) {
    const stick = follow || this.#nearBottom();
    this.#insert(messages);
    this.#update();
    if (stick) this.scrollToLatest();
  }

  /** Add older turns above, keeping what the reader is looking at where it is. */
  prepend(messages, hasMore) {
    const height = this.scroller.scrollHeight;
    const top = this.scroller.scrollTop;
    this.hasMore = hasMore;
    if (messages.length > 0) this.pageStart = messages[0].turn_id;
    this.#insert(messages, { reconcile: false });
    this.#update();
    this.scroller.scrollTop = top + (this.scroller.scrollHeight - height);
  }

  /** "Show earlier" pages before this turn: the start of the history pages loaded so far. */
  get oldestTurnId() {
    return this.pageStart;
  }

  scrollToLatest() {
    this.scroller.scrollTop = this.scroller.scrollHeight;
  }

  clearPending() {
    this.pending.replaceChildren();
    this.waiting.clear();
    this.#update();
  }

  /** Show the question right away, with a placeholder for the answer. */
  addPending(text) {
    const status = element("span", "pending-status", "Отправляется…");
    const question = item("message mine pending", "Вы", status, element("p", "message-body", text));
    const typing = item(
      "message typing",
      "Ассистент",
      element("span", "pending-status", "печатает…"),
      element("p", "message-body typing-dots", "• • •"),
    );
    typing.setAttribute("aria-label", "Ассистент печатает");
    this.pending.append(question, typing);
    this.#update();
    this.scrollToLatest();
    const handle = {
      text,
      remove: () => {
        question.remove();
        typing.remove();
        this.waiting.delete(handle);
        this.#update();
      },
      fail: () => {
        typing.remove();
        question.classList.remove("pending");
        question.classList.add("failed");
        status.textContent = "Ответ не получен";
      },
    };
    this.waiting.add(handle);
    return handle;
  }

  #nearBottom() {
    const { scrollHeight, scrollTop, clientHeight } = this.scroller;
    return scrollHeight - scrollTop - clientHeight <= NEAR_BOTTOM_PX;
  }

  #insert(messages, { reconcile = true } = {}) {
    const fresh = messages.filter((message) => !this.seen.has(message.id));
    for (const message of fresh) {
      this.seen.add(message.id);
      const entry = messageItem(message);
      this.keys.set(entry, sortKey(message));
      this.#place(entry);
      // The stored copy replaces a pending one (also a failed one shown before a poll).
      if (reconcile && message.role === "user" && message.is_mine) {
        for (const handle of [...this.waiting]) {
          if (handle.text === message.text) handle.remove();
        }
      }
    }
  }

  /** Insert in display order; new turns usually go last, so search from the end. */
  #place(entry) {
    const key = this.keys.get(entry);
    let next = null;
    for (let child = this.list.lastElementChild; child; child = child.previousElementSibling) {
      if (!before(key, this.keys.get(child))) break;
      next = child;
    }
    this.list.insertBefore(entry, next);
  }

  #update() {
    this.loadEarlier.hidden = !this.hasMore;
    this.empty.hidden = this.list.children.length + this.pending.children.length > 0;
  }
}
