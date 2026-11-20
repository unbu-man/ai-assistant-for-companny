"use strict";

const el = (id) => document.getElementById(id);
const state = { token: "", company: "", busy: false, config: null, action: null, topics: [], replyLanguage: "en" };
const labels = {
  en: {
    brand: "Company Support", language: "Reply language", title: "How can we help?",
    intro: "Ask about products or get help with your next step.", company: "Company", choose: "Choose a company",
    demo: "Demo mode · Use sample details only.", reset: "New chat", chat: "Support chat",
    technical: "Product and version", product: "Product", version: "Version", send: "Send",
    placeholder: "Ask a question…", message: "Your question", source: "Source",
    business: "Business type", modules: "Modules or workflows", yes: "I agree", no: "No, thanks",
    name: "Name", channel: "Contact method", phone: "Phone", telegram: "Telegram",
    contact: "Number or username", next: "Continue", cancel: "Cancel", save: "Save request",
    sample: "What is the sample label?", price: "How do I request an ERP quote?",
    faq: "Browse verified questions",
    failed: "That didn’t go through. Please try again.", expired: "Start a new chat to continue.",
  },
  km: {
    brand: "ជំនួយអតិថិជន", language: "ភាសាចម្លើយ", title: "តើអាចជួយអ្វីបានខ្លះ?",
    intro: "សួរអំពីផលិតផល ឬស្នើសុំជំនួយសម្រាប់ជំហានបន្ទាប់។", company: "ក្រុមហ៊ុន", choose: "ជ្រើសរើសក្រុមហ៊ុន",
    demo: "ទម្រង់សាកល្បង · សូមប្រើតែទិន្នន័យគំរូ។", reset: "ជជែកថ្មី", chat: "ការជជែកជំនួយ",
    technical: "ផលិតផល និងកំណែ", product: "ផលិតផល", version: "កំណែ", send: "ផ្ញើ",
    placeholder: "សរសេរសំណួរ…", message: "សំណួររបស់អ្នក", source: "ប្រភព",
    business: "ប្រភេទអាជីវកម្ម", modules: "ម៉ូឌុល ឬដំណើរការការងារ", yes: "ខ្ញុំយល់ព្រម", no: "មិនយល់ព្រម",
    name: "ឈ្មោះ", channel: "វិធីទំនាក់ទំនង", phone: "ទូរស័ព្ទ", telegram: "Telegram",
    contact: "លេខទូរស័ព្ទ ឬឈ្មោះអ្នកប្រើ", next: "បន្ត", cancel: "បោះបង់", save: "រក្សាទុកសំណើ",
    sample: "តើស្លាកគំរូជាអ្វី?", price: "តើខ្ញុំអាចស្នើសុំសម្រង់តម្លៃ ERP ដោយរបៀបណា?",
    faq: "មើលសំណួរដែលបានផ្ទៀងផ្ទាត់",
    failed: "មិនអាចផ្ញើបានទេ។ សូមព្យាយាមម្តងទៀត។", expired: "សូមចាប់ផ្តើមការជជែកថ្មីដើម្បីបន្ត។",
  },
};
const words = () => labels[el("language").value === "km" ? "km" : "en"];

function translate() {
  const t = words();
  document.documentElement.lang = el("language").value === "km" ? "km" : "en";
  for (const [id, key] of Object.entries({
    "brand-name": "brand", "language-label": "language", "intro-title": "title",
    "intro-text": "intro", "company-label": "company", "demo-note": "demo",
    "reset": "reset", "chat-title": "chat", "technical-label": "technical",
    "product-label": "product", "version-label": "version", "message-label": "message", "send": "send",
  })) el(id).textContent = t[key];
  const companyPlaceholder = el("company").querySelector('option[value=""]');
  if (companyPlaceholder) companyPlaceholder.textContent = t.choose;
  el("message").placeholder = t.placeholder;
  updateSuggestions();
  updateTopics();
}

function bubble(text, role, lang, citation) {
  const node = document.createElement("div");
  node.className = `bubble ${role}`;
  if (lang) node.lang = lang;
  const content = document.createElement("span");
  content.textContent = text;
  node.append(content);
  if (citation) {
    const source = document.createElement("span");
    source.className = "citation";
    source.textContent = `${labels[lang]?.source || words().source} · ${citation}`;
    node.append(source);
  }
  el("conversation").append(node);
  el("conversation").scrollTop = el("conversation").scrollHeight;
}

function busy(value) {
  state.busy = value;
  el("company").disabled = value || !state.config || state.config.companies.length === 1;
  el("reset").disabled = value || !state.config || !el("company").value;
  el("send").disabled = value || !state.token;
  el("message").disabled = value || !state.token;
  for (const node of el("quote-form").querySelectorAll("button")) node.disabled = value;
  for (const node of el("faq-topics").querySelectorAll("button")) node.disabled = value;
}

function notice(text = "") {
  el("notice").textContent = text;
  el("notice").hidden = !text;
}

async function api(route, body) {
  const options = { headers: {} };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  if (state.token) options.headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(route, options);
  if (!response.ok) {
    const error = new Error("Request failed");
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function updateSuggestions() {
  el("suggestions").replaceChildren();
  if (!state.token || state.action || el("conversation").childElementCount > 1) return;
  const t = words();
  for (const suggestion of state.config.demo ? [t.sample, t.price] : [t.price]) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = suggestion;
    button.addEventListener("click", () => send(suggestion));
    el("suggestions").append(button);
  }
}

function updateTopics() {
  const picker = el("faq-picker");
  const list = el("faq-topics");
  const language = el("language").value === "auto" ? state.replyLanguage : el("language").value;
  picker.hidden = !state.token || !!state.action || state.topics.length === 0;
  el("faq-label").textContent = labels[language].faq;
  picker.lang = language;
  list.replaceChildren();
  if (picker.hidden) return;
  for (const topic of state.topics) {
    const button = document.createElement("button");
    button.type = "button";
    button.disabled = state.busy;
    button.textContent = topic[language];
    button.addEventListener("click", async () => {
      if (state.busy || state.action) return;
      picker.open = false;
      bubble(topic[language], "user", language);
      await perform("topic", { id: topic.id, language });
      el("message").focus();
    });
    list.append(button);
  }
}

async function restart() {
  if (state.busy || !state.config || !el("company").value) return;
  busy(true);
  notice();
  state.token = "";
  state.topics = [];
  el("faq-picker").open = false;
  state.company = el("company").value;
  el("conversation").replaceChildren();
  for (const id of ["message", "product", "version"]) el(id).value = "";
  quoteForm(null);
  try {
    const lang = el("language").value === "km" ? "km" : "en";
    const session = await api(`/api/${state.company}/sessions`, { language: lang });
    state.token = session.token;
    state.replyLanguage = lang;
    state.topics = session.topics || [];
    bubble(session.welcome, "assistant", lang);
  } catch {
    notice(words().failed);
  } finally {
    busy(false);
    updateSuggestions();
    updateTopics();
  }
}

async function perform(route, input) {
  busy(true);
  notice();
  try {
    const result = await api(`/api/${state.company}/${route}`, input);
    state.replyLanguage = result.language;
    bubble(result.text, "assistant", result.language, result.citation);
    quoteForm(result.next_action === "procedure_context" ? null : result.next_action);
    if (result.kind === "knowledge_gap" && !result.next_action && state.topics.length) {
      el("faq-picker").open = true;
    }
    return result;
  } catch (error) {
    notice(error.status === 404 ? words().expired : words().failed);
    return false;
  } finally {
    busy(false);
    updateSuggestions();
    updateTopics();
  }
}

async function send(text) {
  if (state.busy || !state.token || state.action || !text.trim()) return;
  bubble(text, "user");
  const request = { message: text };
  if (el("language").value !== "auto") request.language = el("language").value;
  for (const id of ["product", "version"]) if (el(id).value.trim()) request[id] = el(id).value;
  const result = await perform("chat", request);
  const needsVersion = result?.next_action === "procedure_context";
  el("message").value = !result || needsVersion ? text : "";
  if (needsVersion) {
    el("technical").open = true;
    el(el("product").value ? "version" : "product").focus();
  } else if (!state.action) {
    el("message").focus();
  }
}

function field(name, label, options) {
  const wrapper = document.createElement("label");
  const title = document.createElement("span");
  title.textContent = label;
  const input = document.createElement(options ? "select" : "input");
  input.name = name;
  input.maxLength = 120;
  input.required = true;
  if (options) for (const [value, text] of options) input.add(new Option(text, value));
  wrapper.append(title, input);
  el("quote-fields").append(wrapper);
}

function actionButton(text, onClick, quiet = false) {
  const button = document.createElement("button");
  button.textContent = text;
  button.type = onClick ? "button" : "submit";
  if (quiet) button.className = "quiet";
  if (onClick) button.addEventListener("click", () => { if (!state.busy) onClick(); });
  el("quote-buttons").append(button);
}

function quoteForm(action) {
  state.action = action;
  el("quote-form").hidden = !action;
  el("chat-form").hidden = !!action;
  el("quote-fields").replaceChildren();
  el("quote-buttons").replaceChildren();
  const t = words();
  if (action === "scope") {
    field("business_type", t.business);
    field("modules", t.modules);
    actionButton(t.next);
  } else if (action === "consent") {
    actionButton(t.yes, () => perform("quote/consent", { consent: true }));
    actionButton(t.no, () => perform("quote/consent", { consent: false }), true);
  } else if (action === "contact") {
    field("name", t.name);
    field("channel", t.channel, [["phone", t.phone], ["telegram", t.telegram]]);
    field("contact", t.contact);
    actionButton(t.save);
  }
  if (action) actionButton(t.cancel, () => perform("quote/cancel", {}), true);
}

el("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  send(el("message").value);
});
el("quote-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!state.busy && ["scope", "contact"].includes(state.action)) {
    perform(`quote/${state.action}`, Object.fromEntries(new FormData(event.currentTarget)));
  }
});
el("language").addEventListener("change", () => { translate(); if (state.action && !state.busy) quoteForm(state.action); });
el("company").addEventListener("change", restart);
el("reset").addEventListener("click", restart);

async function start() {
  try {
    state.config = await api("/api/config");
    if (state.config.companies.length > 1) {
      const placeholder = new Option(words().choose, "", true, true);
      placeholder.disabled = true;
      el("company").add(placeholder);
    }
    for (const company of state.config.companies) el("company").add(new Option(company));
    el("demo-note").hidden = !state.config.demo;
    translate();
    busy(false);
    await restart();
  } catch {
    notice(words().failed);
  }
}
start();
