"use strict";

const thread = document.getElementById("thread");
const scroller = document.getElementById("scroll");
const form = document.getElementById("form");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const newChatButton = document.getElementById("new-chat");

// O servidor guarda o histórico; o navegador só precisa lembrar o thread_id.
let threadId = null;
let busy = false;

// Renderiza **negrito** e `código` sem usar innerHTML (evita XSS).
function renderText(element, text) {
  element.replaceChildren();
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    element.append(text.slice(last, match.index));
    const token = match[0];
    const node = document.createElement(token.startsWith("**") ? "strong" : "code");
    node.textContent = token.startsWith("**") ? token.slice(2, -2) : token.slice(1, -1);
    element.append(node);
    last = match.index + token.length;
  }
  element.append(text.slice(last));
}

function addMessage(role, text) {
  document.getElementById("empty")?.remove();
  const bubble = document.createElement("div");
  bubble.className = `msg ${role}`;
  if (role === "assistant") {
    const tools = document.createElement("div");
    tools.className = "tools";
    const body = document.createElement("div");
    body.className = "body";
    bubble.append(tools, body);
    if (text) renderText(body, text);
  } else {
    renderText(bubble, text);
  }
  thread.append(bubble);
  scrollToBottom();
  return bubble;
}

function addToolCall(bubble, name, args) {
  const item = document.createElement("details");
  item.className = "tool";
  const summary = document.createElement("summary");
  summary.textContent = `🔧 ${name}`;
  const detail = document.createElement("pre");
  detail.textContent = `argumentos: ${JSON.stringify(args)}`;
  item.append(summary, detail);
  bubble.querySelector(".tools").append(item);
  scrollToBottom();
  return item;
}

function scrollToBottom() {
  scroller.scrollTop = scroller.scrollHeight;
}

function setBusy(value) {
  busy = value;
  sendButton.disabled = value;
  newChatButton.disabled = value;
}

// Lê um stream SSE vindo de fetch (EventSource não suporta POST).
async function* readServerSentEvents(response) {
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let event = "message";
      const data = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) yield { event, data: JSON.parse(data.join("\n")) };
    }
  }
}

// Token de acesso (quando o servidor define ATLAS_API_TOKEN). Fica só nesta
// aba (sessionStorage) e é enviado no cabeçalho Authorization.
const TOKEN_KEY = "atlas-api-token";

function readToken() {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
}

function saveToken(token) {
  try { sessionStorage.setItem(TOKEN_KEY, token); } catch { /* armazenamento bloqueado */ }
}

// fetch com o token; se o servidor responder 401, pede o token e tenta de novo.
async function apiFetch(url, options = {}) {
  const request = (token) => fetch(url, {
    ...options,
    headers: { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  let response = await request(readToken());
  if (response.status === 401) {
    const token = window.prompt("Este servidor exige um token de acesso:");
    if (token) {
      saveToken(token.trim());
      response = await request(token.trim());
    }
  }
  return response;
}

async function errorDetail(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return "Mensagem inválida.";
  } catch { /* resposta sem JSON */ }
  return `Erro ${response.status}.`;
}

async function send(message) {
  if (busy || !message.trim()) return;
  setBusy(true);
  addMessage("user", message);
  const bubble = addMessage("assistant", "");
  const body = bubble.querySelector(".body");
  body.classList.add("typing");
  body.textContent = "Pensando…";
  let streamed = "";
  const pendingTools = [];

  try {
    const response = await apiFetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(threadId ? { message, thread_id: threadId } : { message }),
    });
    if (response.status === 404) {
      threadId = null;  // conversa expirou ou foi apagada: a próxima mensagem inicia outra
      throw new Error("Esta conversa expirou. Envie a mensagem de novo para começar outra.");
    }
    if (!response.ok) throw new Error(await errorDetail(response));

    for await (const { event, data } of readServerSentEvents(response)) {
      if (event === "token") {
        streamed += data.text;
        body.classList.remove("typing");
        renderText(body, streamed);
        scrollToBottom();
      } else if (event === "tool_call") {
        pendingTools.push(addToolCall(bubble, data.name, data.args));
        streamed = "";  // texto antes de uma ferramenta é só "raciocínio"
      } else if (event === "tool_result") {
        const item = pendingTools.shift();
        if (item) item.querySelector("pre").textContent += `\nresultado: ${data.output}`;
      } else if (event === "done") {
        threadId = data.thread_id;
        body.classList.remove("typing");
        renderText(body, data.answer);
      } else if (event === "error") {
        throw new Error(data.detail);
      }
    }
  } catch (error) {
    bubble.remove();
    addMessage("error", error.message || "Falha de conexão.");
  } finally {
    setBusy(false);
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = input.value;
  input.value = "";
  autoResize();
  send(message);
});

// Enter envia; Shift+Enter quebra linha.
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

function autoResize() {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}
input.addEventListener("input", autoResize);

thread.addEventListener("click", (event) => {
  const button = event.target.closest("[data-suggestion]");
  if (button) send(button.textContent);
});

newChatButton.addEventListener("click", async () => {
  // Apaga o histórico no servidor antes de recarregar a página.
  if (threadId) {
    try {
      await apiFetch(`/threads/${threadId}`, { method: "DELETE" });
    } catch { /* se falhar, a conversa antiga só fica órfã na memória */ }
  }
  window.location.reload();
});
