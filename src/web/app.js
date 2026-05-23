(function () {
  "use strict";

  const state = {
    token: null,
    userName: "",
    services: [],
    currentService: null,
    ws: null,
    sending: false,
  };

  const $ = (id) => document.getElementById(id);
  const views = {
    login: $("login-view"),
    service: $("service-view"),
    chat: $("chat-view"),
  };

  function showView(name) {
    Object.keys(views).forEach((k) =>
      views[k].classList.toggle("hidden", k !== name)
    );
  }

  // Stable color picker for service icons / chat header
  const ICON_PALETTE = [
    "#5667ff", "#10b981", "#f59e0b", "#ef4444",
    "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16",
  ];
  function colorFor(id) {
    let h = 0;
    for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
    return ICON_PALETTE[h % ICON_PALETTE.length];
  }
  function initialOf(name) {
    return (name || "?").trim().charAt(0).toUpperCase() || "?";
  }

  // ── Minimal, XSS-safe Markdown renderer ────────────────────────────────────

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderInline(s) {
    // `s` is already HTML-escaped
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
      if (listType) {
        html += "</" + listType + ">";
        listType = null;
      }
    };
    const parseRow = (l) =>
      l.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());

    while (i < lines.length) {
      const line = lines[i];

      // fenced code block
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

      // table
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

      // heading
      const hm = line.match(/^(#{1,4})\s+(.*)$/);
      if (hm) {
        closeList();
        const level = hm[1].length;
        html += "<h" + level + ">" + renderInline(hm[2]) + "</h" + level + ">";
        i++;
        continue;
      }

      // unordered list
      const um = line.match(/^\s*[-*]\s+(.*)$/);
      if (um) {
        if (listType !== "ul") {
          closeList();
          html += "<ul>";
          listType = "ul";
        }
        html += "<li>" + renderInline(um[1]) + "</li>";
        i++;
        continue;
      }

      // ordered list
      const om = line.match(/^\s*\d+\.\s+(.*)$/);
      if (om) {
        if (listType !== "ol") {
          closeList();
          html += "<ol>";
          listType = "ol";
        }
        html += "<li>" + renderInline(om[1]) + "</li>";
        i++;
        continue;
      }

      // blank line
      if (line.trim() === "") {
        closeList();
        i++;
        continue;
      }

      // paragraph
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

  // ── Chat rendering ─────────────────────────────────────────────────────────

  function clearMessages() {
    $("messages").innerHTML = "";
  }

  function scrollMessages() {
    const m = $("messages");
    m.scrollTop = m.scrollHeight;
  }

  function addUserMessage(text) {
    const row = document.createElement("div");
    row.className = "msg-row user";
    const bubble = document.createElement("div");
    bubble.className = "bubble user";
    bubble.textContent = text;
    row.appendChild(bubble);
    $("messages").appendChild(row);
    scrollMessages();
  }

  function addBotMessage(md) {
    const row = document.createElement("div");
    row.className = "msg-row bot";
    const bubble = document.createElement("div");
    bubble.className = "bubble bot";
    bubble.innerHTML = renderMarkdown(md);
    row.appendChild(bubble);
    $("messages").appendChild(row);
    scrollMessages();
  }

  function addErrorMessage(text) {
    const row = document.createElement("div");
    row.className = "msg-row bot";
    const bubble = document.createElement("div");
    bubble.className = "bubble error";
    bubble.textContent = text;
    row.appendChild(bubble);
    $("messages").appendChild(row);
    scrollMessages();
  }

  function showTypingBubble() {
    if (document.getElementById("typing-bubble")) return;
    const row = document.createElement("div");
    row.id = "typing-bubble";
    row.className = "msg-row bot";
    row.innerHTML =
      '<div class="bubble bot typing">' +
      '<span class="dot"></span><span class="dot"></span><span class="dot"></span>' +
      '</div>';
    $("messages").appendChild(row);
    scrollMessages();
  }

  function hideTypingBubble() {
    const el = document.getElementById("typing-bubble");
    if (el) el.remove();
  }

  function setStatus(text) {
    const s = $("status-line");
    if (text) {
      s.textContent = text;
      s.classList.remove("hidden");
    } else {
      s.textContent = "";
      s.classList.add("hidden");
    }
  }

  function setSending(sending) {
    state.sending = sending;
    $("send-btn").disabled = sending;
    $("chat-input").disabled = sending;
    if (!sending) $("chat-input").focus();
  }

  // ── Service rendering ──────────────────────────────────────────────────────

  function renderServices() {
    const list = $("service-list");
    list.innerHTML = "";

    if (state.services.length === 0) {
      $("service-hint").textContent =
        "접근 가능한 서비스가 없습니다. 관리자에게 문의하세요.";
      return;
    }
    $("service-hint").textContent = "담당하실 서비스를 선택하세요";

    state.services.forEach((svc) => {
      const card = document.createElement("div");
      card.className = "service-card";

      const icon = document.createElement("div");
      icon.className = "service-card-icon";
      icon.style.background = colorFor(svc.id);
      icon.textContent = initialOf(svc.name);

      const textBox = document.createElement("div");
      textBox.className = "service-card-text";
      const name = document.createElement("div");
      name.className = "service-card-name";
      name.textContent = svc.name;
      const desc = document.createElement("div");
      desc.className = "service-card-desc";
      desc.textContent = svc.description || "";
      textBox.appendChild(name);
      textBox.appendChild(desc);

      const arrow = document.createElement("div");
      arrow.className = "service-card-arrow";
      arrow.textContent = "›";

      card.appendChild(icon);
      card.appendChild(textBox);
      card.appendChild(arrow);
      card.addEventListener("click", () => {
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
          state.ws.send(
            JSON.stringify({ type: "select_service", service_id: svc.id })
          );
        }
      });
      list.appendChild(card);
    });
  }

  // ── WebSocket ──────────────────────────────────────────────────────────────

  function connectWebSocket() {
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    const ws = new WebSocket(proto + location.host + "/ws");
    state.ws = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token: state.token }));
    };
    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      handleServerMessage(msg);
    };
    ws.onclose = () => handleDisconnect();
    ws.onerror = () => {};
  }

  function handleDisconnect() {
    if (!state.token) return;
    if (!views.chat.classList.contains("hidden")) {
      hideTypingBubble();
      addErrorMessage("서버와의 연결이 끊어졌습니다. 페이지를 새로고침해 주세요.");
      setStatus("");
      setSending(false);
    } else if (!views.login.classList.contains("hidden")) {
      enableLoginButton();
      $("login-error").textContent = "서버와의 연결이 끊어졌습니다.";
    }
  }

  function handleServerMessage(msg) {
    switch (msg.type) {
      case "auth_success":
        $("service-user").textContent = state.userName + " 님";
        renderServices();
        showView("service");
        break;

      case "auth_error":
        $("login-error").textContent = msg.message || "인증에 실패했습니다.";
        enableLoginButton();
        showView("login");
        break;

      case "service_selected":
        state.currentService = { id: msg.service_id, name: msg.service_name };
        $("chat-service").textContent = msg.service_name;
        const dot = document.querySelector(".mini-logo");
        if (dot) {
          dot.style.background = colorFor(msg.service_id);
          dot.textContent = initialOf(msg.service_name);
        }
        clearMessages();
        hideTypingBubble();
        setStatus("");
        setSending(false);
        addBotMessage(
          "**" +
            msg.service_name +
            "** 서비스에 연결되었습니다.\n\n조회하실 내용을 자연어로 입력해 보세요."
        );
        showView("chat");
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
        if (!views.chat.classList.contains("hidden")) {
          hideTypingBubble();
          setStatus("");
          setSending(false);
          addErrorMessage(msg.message || "오류가 발생했습니다.");
        } else {
          $("service-hint").textContent = msg.message || "오류가 발생했습니다.";
        }
        break;
    }
  }

  // ── Login ──────────────────────────────────────────────────────────────────

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
      connectWebSocket();
    } catch (err) {
      errEl.textContent = "서버에 연결할 수 없습니다.";
      enableLoginButton();
    }
  });

  // ── Logout / navigation ────────────────────────────────────────────────────

  function logout() {
    if (state.ws) {
      try {
        state.ws.close();
      } catch (e) {}
    }
    state.token = null;
    state.ws = null;
    state.currentService = null;
    state.services = [];
    $("login-pw").value = "";
    $("login-error").textContent = "";
    enableLoginButton();
    showView("login");
    $("login-id").focus();
  }

  $("logout-btn").addEventListener("click", logout);
  $("chat-logout-btn").addEventListener("click", logout);
  $("change-service-btn").addEventListener("click", () => {
    renderServices();
    showView("service");
  });

  // ── Sending queries ────────────────────────────────────────────────────────

  function autoGrow(el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }

  function sendQuery() {
    if (state.sending) return;
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

  // ── Init ───────────────────────────────────────────────────────────────────
  $("login-id").focus();
})();
