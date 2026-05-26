(function () {
  "use strict";

  // ── State ────────────────────────────────────────────────────────────────
  const state = {
    token: null,
    userName: "",
    userId: "",
    services: [],         // [{id, name, description, logo_url}]
    currentService: null, // {id, name}
    ws: null,
    sending: false,
    messages: [],         // current view: [{role, content, ts}]
    // Service id the currently in-flight query was issued from. Late-arriving
    // responses get persisted to THIS cache, not whatever the user clicked
    // to in the meantime — keeps a question and its answer in the same bucket.
    pendingService: null,
  };

  const STORE = {
    token: "cs_token",
    userName: "cs_user_name",
    userId: "cs_user_id",
    services: "cs_services",
    lastService: "cs_last_service",
  };

  // localStorage chat-history cache. Keyed per (user, service). Survives
  // refresh, service switch, and reconnect; cleared on logout.
  const CHAT_KEY_PREFIX = "cs_chat_";
  const MAX_HISTORY = 100;
  const MAX_HISTORY_BYTES = 100 * 1024;

  function chatKey(serviceId) {
    return `${CHAT_KEY_PREFIX}${state.userId}_${serviceId}`;
  }
  function saveHistory(serviceId) {
    if (!serviceId || !state.userId) return;
    try {
      let data = state.messages.slice(-MAX_HISTORY);
      let json = JSON.stringify(data);
      // Trim from oldest until under the byte cap (single huge bot reply
      // could blow past MAX_HISTORY entries on byte budget alone).
      while (json.length > MAX_HISTORY_BYTES && data.length > 1) {
        data = data.slice(1);
        json = JSON.stringify(data);
      }
      localStorage.setItem(chatKey(serviceId), json);
    } catch (e) { /* quota exceeded — silently drop */ }
  }
  function loadHistory(serviceId) {
    if (!serviceId || !state.userId) return [];
    try {
      const raw = localStorage.getItem(chatKey(serviceId));
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) { return []; }
  }
  function clearAllChatHistory() {
    try {
      const keys = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith(CHAT_KEY_PREFIX)) keys.push(k);
      }
      keys.forEach((k) => localStorage.removeItem(k));
    } catch (e) {}
  }

  const $ = (id) => document.getElementById(id);
  const views = { login: $("login-view"), app: $("app-view") };

  function showView(name) {
    Object.keys(views).forEach((k) =>
      views[k].classList.toggle("hidden", k !== name)
    );
  }

  // Stable pastel icon palette for services (bg + text Tailwind classes)
  const ICON_PALETTE = [
    ["bg-indigo-50",  "text-indigo-600"],
    ["bg-emerald-50", "text-emerald-600"],
    ["bg-amber-50",   "text-amber-600"],
    ["bg-rose-50",    "text-rose-600"],
    ["bg-sky-50",     "text-sky-600"],
    ["bg-purple-50",  "text-purple-600"],
    ["bg-teal-50",    "text-teal-600"],
  ];
  function iconClassesFor(id) {
    let h = 0;
    for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
    return ICON_PALETTE[h % ICON_PALETTE.length];
  }
  function initialOf(name) {
    return (name || "?").trim().charAt(0).toUpperCase() || "?";
  }

  function saveAuth() {
    localStorage.setItem(STORE.token, state.token);
    localStorage.setItem(STORE.userName, state.userName);
    localStorage.setItem(STORE.userId, state.userId);
    localStorage.setItem(STORE.services, JSON.stringify(state.services));
  }
  function clearAuth() {
    state.token = null;
    state.userName = "";
    state.userId = "";
    state.services = [];
    state.currentService = null;
    localStorage.removeItem(STORE.token);
    localStorage.removeItem(STORE.userName);
    localStorage.removeItem(STORE.userId);
    localStorage.removeItem(STORE.services);
    localStorage.removeItem(STORE.lastService);
  }

  // ── Minimal, XSS-safe Markdown renderer ─────────────────────────────────
  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderInline(s) {
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    s = s.replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]*)\)/g,
      (_, label, url) => {
        // Same-origin /api/download links should open in the same tab so the
        // browser triggers a file download instead of opening a popup tab.
        const isDownload = url.startsWith("/api/download/");
        const attrs = isDownload
          ? `href="${url}" rel="noopener"`
          : `href="${url}" target="_blank" rel="noopener"`;
        return `<a ${attrs}>${label}</a>`;
      }
    );
    return s;
  }

  function renderMarkdown(md) {
    const lines = escapeHtml(md).split("\n");
    let html = "";
    let i = 0;
    let listType = null;
    const closeList = () => {
      if (listType) { html += "</" + listType + ">"; listType = null; }
    };
    const parseRow = (l) =>
      l.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());

    while (i < lines.length) {
      const line = lines[i];

      if (line.trim().startsWith("```")) {
        closeList();
        i++;
        let code = "";
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          code += lines[i] + "\n";
          i++;
        }
        i++;
        html += "<pre><code>" + code.replace(/\n$/, "") + "</code></pre>";
        continue;
      }

      if (
        line.includes("|") &&
        i + 1 < lines.length &&
        lines[i + 1].includes("-") &&
        /^[\s:|-]+$/.test(lines[i + 1])
      ) {
        closeList();
        const headers = parseRow(line);
        i += 2;
        let t = "<table><thead><tr>";
        headers.forEach((h) => (t += "<th>" + renderInline(h) + "</th>"));
        t += "</tr></thead><tbody>";
        while (i < lines.length && lines[i].includes("|")) {
          const cells = parseRow(lines[i]);
          t += "<tr>";
          cells.forEach((c) => (t += "<td>" + renderInline(c) + "</td>"));
          t += "</tr>";
          i++;
        }
        t += "</tbody></table>";
        html += t;
        continue;
      }

      const hm = line.match(/^(#{1,4})\s+(.*)$/);
      if (hm) {
        closeList();
        const level = hm[1].length;
        html += "<h" + level + ">" + renderInline(hm[2]) + "</h" + level + ">";
        i++;
        continue;
      }

      const um = line.match(/^\s*[-*]\s+(.*)$/);
      if (um) {
        if (listType !== "ul") { closeList(); html += "<ul>"; listType = "ul"; }
        html += "<li>" + renderInline(um[1]) + "</li>";
        i++;
        continue;
      }

      const om = line.match(/^\s*\d+\.\s+(.*)$/);
      if (om) {
        if (listType !== "ol") { closeList(); html += "<ol>"; listType = "ol"; }
        html += "<li>" + renderInline(om[1]) + "</li>";
        i++;
        continue;
      }

      if (line.trim() === "") {
        closeList();
        i++;
        continue;
      }

      closeList();
      let para = line;
      i++;
      while (
        i < lines.length &&
        lines[i].trim() !== "" &&
        !lines[i].trim().startsWith("```") &&
        !lines[i].match(/^#{1,4}\s/) &&
        !lines[i].match(/^\s*[-*]\s/) &&
        !lines[i].match(/^\s*\d+\.\s/) &&
        !lines[i].includes("|")
      ) {
        para += " " + lines[i];
        i++;
      }
      html += "<p>" + renderInline(para) + "</p>";
    }
    closeList();
    return html;
  }

  // ── Chat rendering ───────────────────────────────────────────────────────
  function clearMessages() {
    // Wipe message bubbles but keep the empty-state placeholder around
    const messages = $("messages");
    const empty = $("empty-state");
    Array.from(messages.children).forEach((child) => {
      if (child !== empty) child.remove();
    });
  }
  function showEmptyState() { $("empty-state").classList.remove("hidden"); }
  function hideEmptyState() { $("empty-state").classList.add("hidden"); }
  function scrollMessages() {
    const m = $("messages");
    m.scrollTop = m.scrollHeight;
  }

  function addUserMessage(text, serviceId) {
    pushAndRender({ role: "user", content: text, ts: Date.now() }, serviceId);
  }
  function addUserMessageDOM(text) {
    const row = document.createElement("div");
    row.className = "flex justify-end";
    const bubble = document.createElement("div");
    bubble.className =
      "bg-slate-900 text-white rounded-2xl rounded-br-md px-3.5 py-2 " +
      "max-w-[78%] whitespace-pre-wrap text-sm";
    bubble.textContent = text;
    row.appendChild(bubble);
    $("messages").appendChild(row);
    scrollMessages();
  }

  function addBotMessage(md, serviceId) {
    pushAndRender({ role: "bot", content: md, ts: Date.now() }, serviceId);
  }
  function addBotMessageDOM(md) {
    const row = document.createElement("div");
    row.className = "flex group";
    const wrap = document.createElement("div");
    wrap.className = "relative max-w-[82%]";

    const bubble = document.createElement("div");
    bubble.className =
      "bg-white border border-slate-200 shadow-sm text-slate-900 " +
      "rounded-2xl rounded-bl-md px-4 py-3 text-sm bot-content";
    bubble.innerHTML = renderMarkdown(md);

    wrap.appendChild(bubble);
    wrap.appendChild(makeCopyButton(md));
    row.appendChild(wrap);
    $("messages").appendChild(row);
    scrollMessages();
  }

  function makeCopyButton(sourceMarkdown) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.title = "답변 복사";
    btn.setAttribute("aria-label", "답변 복사");
    btn.className =
      "absolute top-1.5 right-1.5 w-7 h-7 rounded-md " +
      "bg-white/80 backdrop-blur border border-slate-200 " +
      "text-slate-500 hover:text-slate-900 hover:bg-white " +
      "opacity-0 group-hover:opacity-100 focus:opacity-100 transition " +
      "flex items-center justify-center";
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
      'class="w-3.5 h-3.5">' +
      '<rect x="9" y="9" width="11" height="11" rx="2"/>' +
      '<path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';

    btn.addEventListener("click", async () => {
      const ok = await copyToClipboard(sourceMarkdown);
      btn.innerHTML = ok
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
          'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" ' +
          'class="w-3.5 h-3.5 text-emerald-600"><path d="M5 13l4 4L19 7"/></svg>'
        : '<span class="text-[10px] text-rose-500">!</span>';
      setTimeout(() => {
        btn.innerHTML =
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
          'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
          'class="w-3.5 h-3.5">' +
          '<rect x="9" y="9" width="11" height="11" rx="2"/>' +
          '<path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
      }, 1400);
    });
    return btn;
  }

  async function copyToClipboard(text) {
    // Use the async Clipboard API where available; fall back to a hidden
    // textarea + document.execCommand for HTTP origins (older Safari etc.)
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) { /* fall through */ }

    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (e) {
      return false;
    }
  }

  function addErrorMessage(text, serviceId) {
    pushAndRender({ role: "error", content: text, ts: Date.now() }, serviceId);
  }
  function addErrorMessageDOM(text) {
    const row = document.createElement("div");
    row.className = "flex";
    const bubble = document.createElement("div");
    bubble.className =
      "bg-red-50 border border-red-200 text-red-600 " +
      "rounded-xl px-4 py-3 max-w-[82%] text-sm";
    bubble.textContent = text;
    row.appendChild(bubble);
    $("messages").appendChild(row);
    scrollMessages();
  }

  function addHistoryDividerDOM() {
    const row = document.createElement("div");
    row.className = "flex items-center gap-2 my-2 text-[11px] text-slate-400";
    row.innerHTML =
      '<div class="flex-1 h-px bg-slate-200"></div>' +
      '<span>여기부터 새 대화 (이전 컨텍스트는 끊겼습니다)</span>' +
      '<div class="flex-1 h-px bg-slate-200"></div>';
    $("messages").appendChild(row);
  }

  function pushAndRender(msg, serviceId) {
    // Default to the user's current view, but allow callers to pin the
    // message to a specific service (used for late-arriving responses
    // after the user has already navigated away to another service).
    const target = serviceId || (state.currentService && state.currentService.id);
    if (!target) return;

    // Only render in the DOM when the message belongs to the visible service.
    if (state.currentService && state.currentService.id === target) {
      state.messages.push(msg);
      renderMessageDOM(msg);
      saveHistory(target);
    } else {
      // User has switched away — append to that service's stored history
      // without touching state.messages (which reflects the visible view).
      const existing = loadHistory(target);
      existing.push(msg);
      const prevView = state.messages;
      state.messages = existing;
      saveHistory(target);
      state.messages = prevView;
    }
  }

  function renderMessageDOM(msg) {
    if (msg.role === "user")  addUserMessageDOM(msg.content);
    else if (msg.role === "bot")   addBotMessageDOM(msg.content);
    else if (msg.role === "error") addErrorMessageDOM(msg.content);
  }

  function replayHistory(history) {
    history.forEach((msg) => renderMessageDOM(msg));
    if (history.length > 0) addHistoryDividerDOM();
  }

  function showTypingBubble() {
    if (document.getElementById("typing-bubble")) return;
    const row = document.createElement("div");
    row.id = "typing-bubble";
    row.className = "flex";
    row.innerHTML =
      '<div class="bg-white border border-slate-200 shadow-sm rounded-2xl rounded-bl-md ' +
      'px-5 py-4 flex gap-1.5 items-center">' +
      '<span class="w-1.5 h-1.5 bg-slate-400 rounded-full typing-dot"></span>' +
      '<span class="w-1.5 h-1.5 bg-slate-400 rounded-full typing-dot" style="animation-delay:0.16s"></span>' +
      '<span class="w-1.5 h-1.5 bg-slate-400 rounded-full typing-dot" style="animation-delay:0.32s"></span>' +
      "</div>";
    $("messages").appendChild(row);
    scrollMessages();
  }

  function hideTypingBubble() {
    const el = document.getElementById("typing-bubble");
    if (el) el.remove();
  }

  function setStatus(text) {
    $("status-text").textContent = text || "";
    $("status-line").style.opacity = text ? "1" : "0";
  }

  function setSending(sending) {
    state.sending = sending;
    updateInputAvailable();
    updateSendButton();
    if (!sending && state.currentService) $("chat-input").focus();
  }

  function updateInputAvailable() {
    const ready = !!state.currentService && !state.sending;
    $("chat-input").disabled = !ready;
    // Send button stays clickable while sending — it morphs into "cancel".
    $("send-btn").disabled = !state.currentService;
  }

  // Inline SVGs so we can swap the button glyph without an extra round-trip.
  const SEND_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" ' +
    'stroke-linecap="round" stroke-linejoin="round" class="w-4 h-4">' +
    '<path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg>'
  );
  const STOP_ICON = (
    '<svg viewBox="0 0 24 24" fill="currentColor" class="w-3 h-3">' +
    '<rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>'
  );

  function updateSendButton() {
    const btn = $("send-btn");
    if (state.sending) {
      btn.innerHTML = STOP_ICON;
      btn.setAttribute("aria-label", "중단");
      btn.title = "처리 중단";
      btn.classList.remove("bg-slate-900", "hover:bg-slate-800");
      btn.classList.add("bg-rose-500", "hover:bg-rose-600");
    } else {
      btn.innerHTML = SEND_ICON;
      btn.setAttribute("aria-label", "전송");
      btn.title = "";
      btn.classList.remove("bg-rose-500", "hover:bg-rose-600");
      btn.classList.add("bg-slate-900", "hover:bg-slate-800");
    }
  }

  function cancelQuery() {
    if (!state.sending) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    state.ws.send(JSON.stringify({ type: "cancel" }));
    setStatus("중단 요청 중...");
  }

  function makeServiceIcon(svc, sizeClasses) {
    // If a logo URL is configured for the service, render an <img>;
    // otherwise fall back to a pastel-colored letter tile.
    if (svc && svc.logo_url) {
      const wrap = document.createElement("div");
      wrap.className = `${sizeClasses} rounded-lg overflow-hidden shrink-0`;
      const img = document.createElement("img");
      img.src = svc.logo_url;
      img.alt = "";
      img.className = "w-full h-full object-cover";
      wrap.appendChild(img);
      return wrap;
    }
    const [bg, text] = iconClassesFor(svc.id);
    const div = document.createElement("div");
    div.className =
      `${sizeClasses} rounded-lg ${bg} ${text} ` +
      "flex items-center justify-center font-semibold text-sm shrink-0";
    div.textContent = initialOf(svc.name);
    return div;
  }

  function setChatHeader(service) {
    // service: null OR {id, name, description, logo_url}
    const iconEl = $("chat-service-icon");
    const nameEl = $("chat-service");
    const descEl = $("chat-description");

    iconEl.replaceChildren();
    if (!service) {
      iconEl.className = "hidden";
      nameEl.textContent = "서비스를 선택해 주세요";
      descEl.textContent = "";
      return;
    }

    if (service.logo_url) {
      iconEl.className = "w-8 h-8 rounded-lg overflow-hidden shrink-0";
      const img = document.createElement("img");
      img.src = service.logo_url;
      img.alt = "";
      img.className = "w-full h-full object-cover";
      iconEl.appendChild(img);
    } else {
      const [bg, text] = iconClassesFor(service.id);
      iconEl.className =
        `w-8 h-8 rounded-lg ${bg} ${text} ` +
        "flex items-center justify-center font-semibold text-sm shrink-0";
      iconEl.textContent = initialOf(service.name);
    }
    nameEl.textContent = service.name;
    descEl.textContent = service.description || "";
  }

  // ── Service sidebar ──────────────────────────────────────────────────────
  function renderServiceList() {
    const list = $("service-list");
    list.innerHTML = "";
    if (state.services.length === 0) {
      list.innerHTML =
        '<div class="text-xs text-slate-400 px-3 py-2">접근 가능한 서비스가 없습니다. 관리자에게 문의해 주세요.</div>';
      return;
    }
    state.services.forEach((svc) => {
      const btn = document.createElement("button");
      btn.dataset.serviceId = svc.id;
      btn.title = svc.description || "";

      btn.appendChild(makeServiceIcon(svc, "w-8 h-8"));

      const textBox = document.createElement("div");
      textBox.className = "flex-1 min-w-0 text-left";

      const name = document.createElement("div");
      name.dataset.role = "name";
      name.className = "text-sm truncate text-slate-700";
      name.textContent = svc.name;

      const desc = document.createElement("div");
      desc.dataset.role = "description";
      desc.className = "text-xs text-slate-400 truncate";
      desc.textContent = svc.description || "";

      textBox.appendChild(name);
      if (svc.description) textBox.appendChild(desc);

      btn.appendChild(textBox);
      btn.addEventListener("click", () => selectService(svc.id));
      list.appendChild(btn);
    });
    updateServiceHighlight();
  }

  function updateServiceHighlight() {
    document.querySelectorAll("#service-list button").forEach((b) => {
      const active = state.currentService && b.dataset.serviceId === state.currentService.id;
      const name = b.querySelector('[data-role="name"]');
      if (active) {
        b.className =
          "w-full flex items-center gap-2.5 px-2 py-2 rounded-lg bg-slate-100 transition";
        if (name) name.className = "text-sm font-semibold text-slate-900 truncate";
      } else {
        b.className =
          "w-full flex items-center gap-2.5 px-2 py-2 rounded-lg hover:bg-slate-50 transition";
        if (name) name.className = "text-sm text-slate-700 truncate";
      }
    });
  }

  function selectService(id) {
    if (state.currentService && state.currentService.id === id) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    // If a query is in flight, cancel it before switching so the answer
    // lands on the originating service's history (via pendingService) and
    // the next query in the new service starts with clean state.
    if (state.sending) {
      state.ws.send(JSON.stringify({ type: "cancel" }));
    }
    state.ws.send(JSON.stringify({ type: "select_service", service_id: id }));
  }

  // ── WebSocket ────────────────────────────────────────────────────────────
  function connectWebSocket() {
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    const ws = new WebSocket(proto + location.host + "/ws");
    state.ws = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token: state.token }));
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      handleServerMessage(msg);
    };
    ws.onclose = () => handleDisconnect();
    ws.onerror = () => {};
  }

  function handleServerMessage(msg) {
    switch (msg.type) {
      case "auth_success": {
        // Auto-select last-used (or first) service
        const last = localStorage.getItem(STORE.lastService);
        const pick = state.services.find((s) => s.id === last) || state.services[0];
        if (pick && !state.currentService) selectService(pick.id);
        break;
      }

      case "auth_error":
        clearAuth();
        showView("login");
        $("login-error").textContent =
          msg.message || "세션이 만료되었습니다. 다시 로그인해 주세요.";
        enableLoginButton();
        $("login-id").focus();
        break;

      case "service_selected": {
        const svc = state.services.find((s) => s.id === msg.service_id)
                 || { id: msg.service_id, name: msg.service_name, description: "", logo_url: "" };
        state.currentService = { id: svc.id, name: svc.name };
        localStorage.setItem(STORE.lastService, svc.id);
        setChatHeader(svc);
        updateServiceHighlight();
        clearMessages();
        hideTypingBubble();
        setStatus("");
        setSending(false);

        // Replay cached chat for this service. Claude's conversation context
        // resets on switch (server-side), but the user can still read what
        // they previously asked here.
        const history = loadHistory(svc.id);
        state.messages = history.slice();
        if (history.length > 0) {
          hideEmptyState();
          replayHistory(history);
        } else {
          showEmptyState();
        }
        $("chat-input").focus();
        break;
      }

      case "status":
        setStatus(msg.message || "");
        break;

      case "response": {
        hideTypingBubble();
        setStatus("");
        setSending(false);
        const target = state.pendingService;
        state.pendingService = null;
        addBotMessage(msg.message || "", target);
        break;
      }

      case "error":
        if (!views.app.classList.contains("hidden")) {
          hideTypingBubble();
          setStatus("");
          setSending(false);
          const target = state.pendingService;
          state.pendingService = null;
          addErrorMessage(msg.message || "처리 중 오류가 발생했습니다.", target);
        }
        break;

      case "ping":
        // Server-side keepalive during long queries — reply so the connection
        // looks alive to any intermediary that drops idle sockets.
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
          state.ws.send(JSON.stringify({ type: "pong" }));
        }
        break;
    }
  }

  function handleDisconnect() {
    if (!state.token) return;
    if (!views.app.classList.contains("hidden")) {
      if (!state.currentService) {
        // never reached a working state — bounce back to login
        clearAuth();
        showView("login");
        enableLoginButton();
        $("login-error").textContent = "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.";
      } else {
        hideTypingBubble();
        addErrorMessage("서버 연결이 끊어졌습니다. 페이지를 새로고침해 주세요.");
        setStatus("");
        setSending(false);
      }
    } else if (!views.login.classList.contains("hidden")) {
      enableLoginButton();
      $("login-error").textContent = "서버 연결이 끊어졌습니다.";
    }
  }

  // ── Login / logout ───────────────────────────────────────────────────────
  function enableLoginButton() {
    const btn = $("login-form").querySelector("button");
    btn.disabled = false;
    btn.textContent = "로그인";
  }

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = $("login-id").value.trim();
    const pw = $("login-pw").value;
    const errEl = $("login-error");
    const btn = e.target.querySelector("button");

    if (!id || !pw) {
      errEl.textContent = "아이디와 비밀번호를 모두 입력해 주세요.";
      return;
    }
    errEl.textContent = "";
    btn.disabled = true;
    btn.textContent = "로그인 중...";

    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: id, password: pw }),
      });
      const data = await res.json();
      if (!res.ok) {
        errEl.textContent = data.error || "로그인에 실패했습니다. 다시 시도해 주세요.";
        enableLoginButton();
        return;
      }
      state.token = data.token;
      state.userName = data.user_name;
      state.userId = data.user_id;
      state.services = data.services || [];
      saveAuth();
      enterApp();
      connectWebSocket();
    } catch (err) {
      errEl.textContent = "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.";
      enableLoginButton();
    }
  });

  function logout() {
    if (state.ws) { try { state.ws.close(); } catch (e) {} }
    state.ws = null;
    clearAllChatHistory();   // wipe per-service caches before user list changes
    clearAuth();
    state.messages = [];
    state.pendingService = null;
    $("login-pw").value = "";
    $("login-error").textContent = "";
    enableLoginButton();
    showView("login");
    $("login-id").focus();
  }
  $("logout-btn").addEventListener("click", logout);

  // ── Sending queries ──────────────────────────────────────────────────────
  function autoGrow(el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }

  function sendQuery() {
    if (state.sending) return;
    if (!state.currentService) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      addErrorMessage("서버 연결이 끊어졌습니다. 페이지를 새로고침해 주세요.");
      return;
    }
    const input = $("chat-input");
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    autoGrow(input);
    hideEmptyState();
    // Pin this turn to the originating service so a late response can't
    // land in whichever service the user clicked over to in the meantime.
    state.pendingService = state.currentService.id;
    addUserMessage(text, state.pendingService);
    showTypingBubble();
    setSending(true);
    setStatus("");
    state.ws.send(JSON.stringify({ type: "query", message: text }));
  }

  $("send-btn").addEventListener("click", () => {
    if (state.sending) cancelQuery();
    else sendQuery();
  });
  $("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendQuery();
    }
  });
  $("chat-input").addEventListener("input", (e) => autoGrow(e.target));

  // ── Entry into the app shell (after login or after restoring from storage) ──
  function enterApp() {
    $("user-name").textContent = state.userName;
    $("user-id").textContent = state.userId;
    renderServiceList();
    clearMessages();
    state.messages = [];
    setStatus("");
    state.currentService = null;
    setChatHeader(null);
    hideEmptyState();
    updateInputAvailable();
    showView("app");
  }

  // ── Initialize ───────────────────────────────────────────────────────────
  function initialize() {
    const token = localStorage.getItem(STORE.token);
    if (!token) {
      showView("login");
      $("login-id").focus();
      return;
    }
    // Restore from localStorage and try to re-auth via WebSocket.
    // If the token is no longer valid (e.g. server restarted), auth_error
    // will bounce us back to the login screen.
    state.token = token;
    state.userName = localStorage.getItem(STORE.userName) || "";
    state.userId = localStorage.getItem(STORE.userId) || "";
    try {
      state.services = JSON.parse(localStorage.getItem(STORE.services) || "[]");
    } catch (e) {
      state.services = [];
    }
    enterApp();
    connectWebSocket();
  }

  initialize();

  // PWA service worker — enables the "install app" prompt in browsers
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    });
  }
})();
