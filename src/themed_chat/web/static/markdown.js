// A small, safe Markdown renderer. It builds DOM nodes with textContent only (never innerHTML),
// so model output cannot inject markup or scripts. Supported: paragraphs, headings, bullet and
// numbered lists, quotes, rules, fenced code, **bold**, *italic* / _italic_, `code`.
// Links are shown as plain text; anything else stays literal text.

const FENCE = /^\s*```/;
const HEADING = /^\s{0,3}#{1,6}\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;

// One alternative per group: code, bold (**), bold (__), italic (*), italic (_), link.
const INLINE = new RegExp(
  [
    "`([^`\\n]+)`",
    "\\*\\*(?=\\S)(.+?)(?<=\\S)\\*\\*",
    "(?<![\\p{L}\\p{N}_])__(?=\\S)(.+?)(?<=\\S)__(?![\\p{L}\\p{N}_])",
    "\\*(?=[^\\s*])([^*\\n]+?)(?<=[^\\s*])\\*",
    "(?<![\\p{L}\\p{N}_])_(?=[^\\s_])([^_\\n]+?)(?<=[^\\s_])_(?![\\p{L}\\p{N}_])",
    "\\[([^\\]\\n]+)\\]\\(([^)\\s]+)\\)",
  ].join("|"),
  "u",
);

function element(name, className) {
  const node = document.createElement(name);
  if (className) node.className = className;
  return node;
}

function appendInline(parent, text) {
  let rest = text;
  while (rest) {
    const match = INLINE.exec(rest);
    if (!match) break;
    if (match.index > 0) parent.append(rest.slice(0, match.index));
    const [, code, bold, underscoreBold, italic, underscoreItalic, label, address] = match;
    if (code !== undefined) {
      const node = element("code");
      node.textContent = code;
      parent.append(node);
    } else if (bold !== undefined || underscoreBold !== undefined) {
      const node = element("strong");
      appendInline(node, bold ?? underscoreBold);
      parent.append(node);
    } else if (italic !== undefined || underscoreItalic !== undefined) {
      const node = element("em");
      appendInline(node, italic ?? underscoreItalic);
      parent.append(node);
    } else {
      parent.append(`${label} (${address})`);
    }
    rest = rest.slice(match.index + match[0].length);
  }
  if (rest) parent.append(rest);
}

function appendLines(parent, lines) {
  lines.forEach((line, index) => {
    if (index > 0) parent.append(element("br"));
    appendInline(parent, line);
  });
}

function takeWhile(lines, start, test) {
  const taken = [];
  for (let index = start; index < lines.length; index += 1) {
    const match = test(lines[index]);
    if (match === null) break;
    taken.push(match);
  }
  return taken;
}

const matcher = (pattern) => (line) => pattern.exec(line)?.[1] ?? null;
const startsBlock = (line) =>
  FENCE.test(line) || HEADING.test(line) || BULLET.test(line) || NUMBERED.test(line)
  || QUOTE.test(line) || RULE.test(line);

/** Returns a DocumentFragment with the rendered blocks. */
export function renderMarkdown(source) {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const fragment = document.createDocumentFragment();
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
    } else if (FENCE.test(line)) {
      const code = [];
      index += 1;
      while (index < lines.length && !FENCE.test(lines[index])) code.push(lines[index++]);
      index += 1; // The closing fence; a missing one simply ends the block at the end of text.
      const pre = element("pre");
      const node = element("code");
      node.textContent = code.join("\n");
      pre.append(node);
      fragment.append(pre);
    } else if (RULE.test(line)) {
      fragment.append(element("hr"));
      index += 1;
    } else if (HEADING.test(line)) {
      const paragraph = element("p", "md-heading");
      const strong = element("strong");
      appendInline(strong, HEADING.exec(line)[1]);
      paragraph.append(strong);
      fragment.append(paragraph);
      index += 1;
    } else if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = !BULLET.test(line);
      const items = takeWhile(lines, index, matcher(ordered ? NUMBERED : BULLET));
      const list = element(ordered ? "ol" : "ul");
      // A list interrupted by nested items must keep counting.
      if (ordered) list.start = Number(/\d+/.exec(line)[0]);
      for (const item of items) {
        const entry = element("li");
        appendInline(entry, item);
        list.append(entry);
      }
      fragment.append(list);
      index += items.length;
    } else if (QUOTE.test(line)) {
      const quoted = takeWhile(lines, index, matcher(QUOTE));
      const quote = element("blockquote");
      appendLines(quote, quoted);
      fragment.append(quote);
      index += quoted.length;
    } else {
      const paragraph = [line];
      index += 1;
      while (index < lines.length && lines[index].trim() && !startsBlock(lines[index])) {
        paragraph.push(lines[index++]);
      }
      const node = element("p");
      appendLines(node, paragraph);
      fragment.append(node);
    }
  }
  return fragment;
}
