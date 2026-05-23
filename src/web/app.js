(function () {
  "use strict";

  // ── State ────────────────────────────────────────────────────────────────
  const state = {
    token: null,
    userName: "",
    services: [],         // [{id, name, description}]
    currentService: null, // {id, name}
    ws: null,
    sending: false,
  };

  const STORE = {
    token: "cs_token",
    userName: "cs_user_name",
    services: "cs_services",
    lastService: "cs_last_service",
  };

  const $ = (id) => document.getElementById(id);
  const views = { login: $("login-view"), app: $("app-view") };

  function showView(name) {
    Object.keys(views).forEach((k) =>
      views[k].classList.toggle("hidden", k !== name)
    );
  }

  function saveAuth() {
    localStorage.setItem(STORE.token, state.token);
    localStorage.setItem(STORE.userName, state.userName);
    localStorage.setItem(STORE.services, JSON.stringify(state.services));
  }
  function clearAuth() {
    state.token = null;
    state.userName = "";
    state.services = [];
    state.currentService = null;
    localStorage.removeItem(STORE.token);
    localStorage.removeItem(STORE.userName);
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
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>'
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
  function clearMessages() { $("messages").innerHTML = ""; }
  function scrollMessages() {
    const m = $("messages");
    m.scrollTop = m.scrollHeight;
  }

  function addUserMessage(text) {
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

  function addBotMessage(md) {
    const row = document.createElement("div");
    row.className = "flex";
    const bubble = document.createElement("div");
    bubble.className =
      "bg-slate-50 border border-slate-200 text-slate-900 " +
      "rounded-2xl rounded-bl-md px-4 py-3 max-w-[82%] text-sm bot-content";
    bubble.innerHTML = renderMarkdown(md);
    row.appendChild(bubble);
    $("messages").appendChild(row);
    scrollMessages();
  }

  function addErrorMessage(text) {
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

  function showTypingBubble() {
    if (document.getElementById("typing-bubble")) return;
    const row = document.createElement("div");
    row.id = "typing-bubble";
    row.className = "flex";
    row.innerHTML =
      '<div class="bg-slate-50 border border-slate-200 rounded-2xl rounded-bl-md ' +
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
    const s = $("status-line");
    if (text) { s.textContent = text; s.classList.remove("hidden"); }
    else      { s.textContent = "";   s.classList.add("hidden"); }
  }

  function setSending(sending) {
    state.sending = sending;
    updateInputAvailable();
    if (!sending && state.currentService) $("chat-input").focus();
  }

  function updateInputAvailable() {
    const ready = !!state.currentService && !state.sending;
    $("chat-input").disabled = !ready;
    $("send-btn").disabled = !ready;
  }

  // ── Service sidebar ──────────────────────────────────────────────────────
  function renderServiceList() {
    const list = $("service-list");
    list.innerHTML = "";
    if (state.services.length === 0) {
      list.innerHTML =
        '<div class="text-xs text-slate-400 px-3 py-2">접근 가능한 서비스가 없습니다.</div>';
      return;
    }
    state.services.forEach((svc) => {
      const btn = document.createElement("button");
      btn.dataset.serviceId = svc.id;
      btn.title = svc.description || "";
      btn.textContent = svc.name;
      // default styling; updateServiceHighlight() overrides for the active one
      btn.className =
        "w-full text-left px-3 py-1.5 rounded-md text-sm text-slate-600 " +
        "hover:bg-slate-200/60 hover:text-slate-900 transition truncate";
      btn.addEventListener("click", () => selectService(svc.id));
      list.appendChild(btn);
    });
    updateServiceHighlight();
  }

  function updateServiceHighlight() {
    document.querySelectorAll("#service-list button").forEach((b) => {
      const active = state.currentService && b.dataset.serviceId === state.currentService.id;
      b.className = active
        ? "w-full text-left px-3 py-1.5 rounded-md text-sm font-medium bg-slate-200 text-slate-900 truncate"
        : "w-full text-left px-3 py-1.5 rounded-md text-sm text-slate-600 hover:bg-slate-200/60 hover:text-slate-900 transition truncate";
    });
  }

  function selectService(id) {
    if (state.currentService && state.currentService.id === id) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
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
          msg.message || "세션이 만료되었습니다. 다시 로그인하세요.";
        enableLoginButton();
        $("login-id").focus();
        break;

      case "service_selected":
        state.currentService = { id: msg.service_id, name: msg.service_name };
        localStorage.setItem(STORE.lastService, msg.service_id);
        $("chat-service").textContent = msg.service_name;
        updateServiceHighlight();
        clearMessages();
        hideTypingBubble();
        setStatus("");
        setSending(false);
        addBotMessage("**" + msg.service_name + "** — 질문을 입력해 보세요.");
        $("chat-input").focus();
        break;

      case "status":
        setStatus(msg.message || "");
        break;

      case "response":
        hideTypingBubble();
        setStatus("");
        setSending(false);
        addBotMessage(msg.message || "");
        break;

      case "error":
        if (!views.app.classList.contains("hidden")) {
          hideTypingBubble();
          setStatus("");
          setSending(false);
          addErrorMessage(msg.message || "오류가 발생했습니다.");
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
        $("login-error").textContent = "서버와 연결할 수 없습니다.";
      } else {
        hideTypingBubble();
        addErrorMessage("서버와의 연결이 끊어졌습니다. 페이지를 새로고침해 주세요.");
        setStatus("");
        setSending(false);
      }
    } else if (!views.login.classList.contains("hidden")) {
      enableLoginButton();
      $("login-error").textContent = "서버와의 연결이 끊어졌습니다.";
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
      errEl.textContent = "아이디와 비밀번호를 입력하세요.";
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
        errEl.textContent = data.error || "로그인에 실패했습니다.";
        enableLoginButton();
        return;
      }
      state.token = data.token;
      state.userName = data.user_name;
      state.services = data.services || [];
      saveAuth();
      enterApp();
      connectWebSocket();
    } catch (err) {
      errEl.textContent = "서버에 연결할 수 없습니다.";
      enableLoginButton();
    }
  });

  function logout() {
    if (state.ws) { try { state.ws.close(); } catch (e) {} }
    state.ws = null;
    clearAuth();
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
      addErrorMessage("서버와 연결되어 있지 않습니다. 페이지를 새로고침해 주세요.");
      return;
    }
    const input = $("chat-input");
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    autoGrow(input);
    addUserMessage(text);
    showTypingBubble();
    setSending(true);
    setStatus("");
    state.ws.send(JSON.stringify({ type: "query", message: text }));
  }

  $("send-btn").addEventListener("click", sendQuery);
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
    renderServiceList();
    clearMessages();
    setStatus("");
    state.currentService = null;
    $("chat-service").textContent = "서비스를 선택하세요";
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
    try {
      state.services = JSON.parse(localStorage.getItem(STORE.services) || "[]");
    } catch (e) {
      state.services = [];
    }
    enterApp();
    connectWebSocket();
  }

  initialize();
})();
