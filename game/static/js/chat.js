/**
 * =========================================================================
 * CHAT SYSTEM LOGIC
 * =========================================================================
 * Handles real-time chat functionality for the game interface:
 * - Message polling and rendering
 * - Input handling and validation
 * - Auto-scrolling and UI updates
 */

let CHAT_POLL_MS = 2000;
let chatPoller = null;

function getChatEls() {
    return {
        box: document.getElementById("chatMessages"),
        input: document.getElementById("chatInput"),
        sendBtn: document.getElementById("chatSendBtn"),
        form: document.getElementById("chatForm"),
        liveCount: document.getElementById("chatLiveCount"),
    };
}

/**
 * Escapes HTML characters to prevent XSS.
 * @param {string} str - The raw string to escape.
 * @returns {string} The escaped string.
 */
function escapeHtmlChat(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function safeInitial(name) {
    const t = (name || "").trim();
    return t ? t[0].toUpperCase() : "?";
}

function chatScrollToBottom() {
    const { box } = getChatEls();
    if (!box) return;
    box.scrollTop = box.scrollHeight;
}

/**
 * Toggles the send button state based on input content.
 */
function setSendEnabled() {
    const { input, sendBtn } = getChatEls();
    if (!input || !sendBtn) return;
    sendBtn.disabled = (input.value || "").trim().length === 0;
}

function renderChatMessages(messages) {
    const { box, liveCount } = getChatEls();
    if (!box) return;

    box.innerHTML = "";

    for (const m of messages) {
        const row = document.createElement("div");
        row.className = m.is_you ? "chat-row you" : "chat-row";
        row.setAttribute("data-initial", safeInitial(m.user));

        row.innerHTML = `<div class="chat-bubble">${escapeHtmlChat(m.message)}</div>`;
        box.appendChild(row);
    }

    if (liveCount) liveCount.textContent = String(messages.length);
    chatScrollToBottom();
}

/**
 * Polls the server for new chat messages.
 * @param {string} gameId - The current game ID.
 */
async function fetchChat(gameId) {
    const res = await fetch(`/games/${gameId}/chat/messages/`, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || !data) return;

    const messages = Array.isArray(data.messages) ? data.messages : [];
    renderChatMessages(messages);
}

function getCSRFTokenChat() {
    const name = "csrftoken";
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (let c of cookies) {
        c = c.trim();
        if (c.startsWith(name + "=")) return decodeURIComponent(c.substring(name.length + 1));
    }
    return "";
}

async function sendChat(gameId, text) {
    const res = await fetch(`/games/${gameId}/chat/send/`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCSRFTokenChat(),
            "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({ message: text }),
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        const msg = (data && data.detail) ? data.detail : `Chat send failed (${res.status})`;
        throw new Error(msg);
    }
    return data;
}

/**
 * Initializes the chat system, asking for DOM elements and setting up listeners.
 * Configures polling interval and form submission.
 */
function initChat() {
    const gameId = window.GAME_ID;
    const { input, sendBtn, form } = getChatEls();
    // Return early if Chat UI elements are not present
    if (!gameId || !input || !sendBtn || !form) return;

    // Initial fetch
    fetchChat(gameId);

    // Setup polling
    if (chatPoller) clearInterval(chatPoller);
    chatPoller = setInterval(() => fetchChat(gameId), CHAT_POLL_MS);

    // Input listeners
    input.addEventListener("input", setSendEnabled);

    // Form submission
    form.addEventListener("submit", async (e) => {
        e.preventDefault();

        const text = (input.value || "").trim();
        if (!text) return;

        sendBtn.disabled = true;

        try {
            await sendChat(gameId, text);
            input.value = "";
            setSendEnabled();
            await fetchChat(gameId);
            input.focus();
        } catch (err) {
            alert(err?.message || "Chat error");
            setSendEnabled();
        }
    });

    // Enter key support
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            form.requestSubmit();
        }
    });

    // Initial state
    setSendEnabled();
}

// Global Export
window.initChat = initChat;
