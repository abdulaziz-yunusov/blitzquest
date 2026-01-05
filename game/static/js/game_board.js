// ---------- helpers ----------

function getCookie(name) {
    if (!document.cookie) return null;
    const cookies = document.cookie.split(";").map(c => c.trim());
    for (const c of cookies) {
        if (c.startsWith(name + "=")) {
            return decodeURIComponent(c.substring(name.length + 1));
        }
    }
    return null;
}

function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
function getCSRFToken() {
    // Django default cookie name:
    const name = "csrftoken";
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (let c of cookies) {
        c = c.trim();
        if (c.startsWith(name + "=")) return decodeURIComponent(c.substring(name.length + 1));
    }
    return "";
}

function getGameIdFromPage() {
    // 1) if you already set window.GAME_ID, use it
    if (typeof window.GAME_ID !== "undefined" && window.GAME_ID) return window.GAME_ID;

    // 2) try data-game-id on body or board root
    const el =
        document.querySelector("[data-game-id]") ||
        document.body;

    const v = el ? el.getAttribute("data-game-id") : null;
    if (v && /^\d+$/.test(v)) return Number(v);

    // 3) parse from URL like /games/69/...
    const m = window.location.pathname.match(/\/games\/(\d+)\b/);
    if (m) return Number(m[1]);

    return null;
}

async function safeJson(res) {
    try {
        return await res.json();
    } catch {
        return null;
    }
}

function getDiceEls() {
    return {
        die: document.getElementById("bq-die-1"),
        diceText: document.getElementById("dice-text"),
        diceDisplay: document.getElementById("dice-display"),
    };
}

function toggleDiceClasses(die) {
    if (!die) return;
    die.classList.toggle("odd-roll");
    die.classList.toggle("even-roll");
}

function animateDieTo(value) {
    const { die } = getDiceEls();
    if (!die) return;
    toggleDiceClasses(die);
    die.dataset.roll = String(value);
}

/**
 * Applies server response after buy/sell/close.
 * Expected shape: { game_state: ... }
 * This tries to integrate with your existing code:
 * - If you have a function like renderGameState(state), it uses it.
 * - If you have a global setter, it uses it.
 */
async function applyGameStateUpdate(payload) {
    const state = payload && payload.game_state ? payload.game_state : null;
    if (!state) return;

    // If your code keeps a global `GAME_STATE`, update it
    window.GAME_STATE = state;

    // If you already have a renderer, call it
    if (typeof window.renderGameState === "function") {
        window.renderGameState(state);
    } else if (typeof window.updateUIFromState === "function") {
        window.updateUIFromState(state);
    } else if (typeof window.onGameState === "function") {
        window.onGameState(state);
    }

    if (state.pending_shop) {
        showShopModal(state.pending_shop, state);
    } else {
        hideShopModal();
    }
}
// ---------- UI: question modal ----------
function showQuestionModal(q, state) {
    const modal = document.getElementById("questionModal");
    const prompt = document.getElementById("qPrompt");
    const choicesWrap = document.getElementById("qChoices");
    const feedback = document.getElementById("qFeedback");
    const changeBtn = document.getElementById("changeQuestionBtn");

    prompt.textContent = q.prompt || "";
    feedback.textContent = "";
    choicesWrap.innerHTML = "";

    const gameId = window.GAME_ID;

    // detect change-question card
    const cards = state && Array.isArray(state.your_cards) ? state.your_cards : [];
    const canChange = !!(q && !q.changed_once);
    const changeCard = canChange
        ? cards.find(c =>
            (c.effect_type || "").toLowerCase() === "change_question" ||
            (c.code || "").toLowerCase() === "change_question"
        )
        : null;

    // header button behavior
    if (changeBtn) {
        if (!canChange) {
            changeBtn.textContent = "🔄 Used";
            changeBtn.disabled = true;
        } else if (!changeCard) {
            changeBtn.textContent = "🔄 No card";
            changeBtn.disabled = true;
        } else {
            changeBtn.textContent = "🔄 Change";
            changeBtn.disabled = false;
        }
    }

    changeBtn.onclick = async () => {
        if (!canChange || !changeCard) return;

        // disable interactions while changing
        changeBtn.disabled = true;
        Array.from(choicesWrap.querySelectorAll("button")).forEach(b => (b.disabled = true));
        feedback.textContent = "Changing question...";

        try {
            await useCard(gameId, changeCard.id);
            // useCard() should refresh state and call showQuestionModal again
        } catch (e) {
            console.error(e);
            feedback.textContent = "Could not change question.";
            changeBtn.disabled = false;
            Array.from(choicesWrap.querySelectorAll("button")).forEach(b => (b.disabled = false));
        }
    };

    // render options (IMPORTANT: class must be qchoice-btn)
    (q.choices || []).forEach((text, idx) => {
        const btn = document.createElement("button");
        btn.className = "qchoice-btn";
        btn.type = "button";
        btn.dataset.qidx = String(idx);
        btn.textContent = text;

        btn.addEventListener("click", async () => {
            Array.from(choicesWrap.querySelectorAll("button")).forEach(b => b.disabled = true);
            changeBtn.disabled = true;
            try {
                const resp = await fetch(`/games/${gameId}/answer_question/`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCookie("csrftoken") || "",
                    },
                    body: JSON.stringify({ choice_index: idx }),
                });

                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) {
                    feedback.textContent = (data && data.detail) ? data.detail : `Error: ${resp.status}`;
                    Array.from(choicesWrap.querySelectorAll("button")).forEach(b => b.disabled = false);
                    return;
                }

                const correct = data?.result?.correct;
                feedback.textContent = correct ? "Correct: +1 coin, +1 HP" : "Wrong: -1 HP";

                // Visual feedback (green/red) + show correct option if wrong
                try {
                    if (correct) {
                        btn.classList.add("correct");
                    } else {
                        btn.classList.add("wrong");
                        const correctIdx = (q && typeof q.correct_index === "number") ? q.correct_index : null;
                        if (correctIdx !== null) {
                            const correctBtn = choicesWrap.querySelector(`button[data-qidx="${correctIdx}"]`);
                            if (correctBtn) correctBtn.classList.add("correct");
                        }
                    }
                } catch (e) { /* ignore styling errors */ }

                // refresh UI
                if (data.game_state) {
                    updateBoardUI(data.game_state);
                    updatePlayersUI(data.game_state);
                    updateDiceUI(data.game_state);
                    renderPlayerTokens(data.game_state);
                    renderQuestionUI(data.game_state);
                    renderInventoryUI(data.game_state);

                } else {
                    fetchGameState(gameId);
                }

            } catch (e) {
                console.error(e);
                feedback.textContent = "Network error.";
                Array.from(choicesWrap.querySelectorAll("button")).forEach(b => b.disabled = false);
            }
        });

        choicesWrap.appendChild(btn);
    });

    modal.classList.remove("is-hidden");
    modal.setAttribute("aria-hidden", "false");
}


function hideQuestionModal() {
    const modal = document.getElementById("questionModal");
    if (!modal) return;
    modal.classList.add("is-hidden");
    modal.setAttribute("aria-hidden", "true");
}

function renderQuestionUI(state) {
    if (!state) return;

    if (state.pending_question) {
        showQuestionModal(state.pending_question, state);
    } else {
        hideQuestionModal();
    }
}

let SHOP_IS_OPEN = false;

/**
 * Opens the shop modal for the current player.
 * @param {Object} pendingShop - state.pending_shop (only present for the owning player)
 * @param {Object} gameState - whole game_state (used to show coins + inventory)
 */
function showShopModal(pendingShop, gameState) {
    const modal = document.getElementById("shopModal");
    if (!modal) return;

    SHOP_IS_OPEN = true;

    // show modal
    modal.classList.remove("is-hidden");
    modal.setAttribute("aria-hidden", "false");

    // fill coins
    const coinsEl = document.getElementById("sCoins");
    if (coinsEl) {
        const me = (gameState && Array.isArray(gameState.players)) ? gameState.players.find(p => p.is_you) : null;
        coinsEl.textContent = me && typeof me.coins !== "undefined" ? me.coins : "0";
    }

    // clear feedback
    const feedback = document.getElementById("shopFeedback");
    if (feedback) feedback.textContent = "";

    // render offers
    const offersWrap = document.getElementById("shopOffers");
    if (offersWrap) {
        offersWrap.innerHTML = "";
        const offers = (pendingShop && pendingShop.offers) ? pendingShop.offers : [];

        if (!offers.length) {
            offersWrap.innerHTML = `<div class="muted">No items available.</div>`;
        } else {
            offers.forEach((o) => {
                const name = o.name || o.code || "Card";
                const desc = o.description || "";
                const cost = Number(o.cost || 0);

                const row = document.createElement("div");
                row.className = "soffer";

                row.innerHTML = `
                    <div>
                        <div class="soffer-title">${escapeHtml(name)}</div>
                        <div class="soffer-desc">${escapeHtml(desc)}</div>
                    </div>
                    <div class="soffer-meta">
                        <span class="sprice">🪙 ${cost}</span>
                        <button type="button" class="qhead-btn" data-buy="${o.card_type_id}">
                            Buy
                        </button>
                    </div>
                `;

                offersWrap.appendChild(row);
            });
        }
    }

    // render sell list from inventory (server exposes `your_cards` at top-level)
    const sellWrap = document.getElementById("shopSellList");
    if (sellWrap) {
        sellWrap.innerHTML = "";
        const inv = (gameState && Array.isArray(gameState.your_cards)) ? gameState.your_cards : [];

        if (!inv.length) {
            sellWrap.innerHTML = `<div class="muted">You have no cards to sell.</div>`;
        } else {
            inv.forEach((c) => {
                const instId = c.id;
                const title = c.name || c.code || "Card";
                const desc = c.description || "";

                const row = document.createElement("div");
                row.className = "soffer";
                row.innerHTML = `
                    <div>
                        <div class="soffer-title">${escapeHtml(title)}</div>
                        <div class="soffer-desc">${escapeHtml(desc)}</div>
                    </div>
                    <div class="soffer-meta">
                        <button type="button" class="qhead-btn" data-sell="${instId}">
                            Sell
                        </button>
                    </div>
                `;
                sellWrap.appendChild(row);
            });
        }
    }

    // bind handlers (event delegation, safe to re-call)
    modal.onclick = async (e) => {
        const btn = e.target.closest("button");
        if (!btn) return;

        // buy
        const buyId = btn.getAttribute("data-buy");
        if (buyId) {
            await shopBuyCard(Number(buyId));
            return;
        }

        // sell
        const sellId = btn.getAttribute("data-sell");
        if (sellId) {
            await shopSellCard(Number(sellId));
            return;
        }
    };

    // close button (end turn)
    const closeBtn = document.getElementById("shopCloseBtn");
    if (closeBtn) {
        closeBtn.onclick = async () => {
            await shopClose();
        };
    }

    // Optional: block closing via ESC / backdrop (turn should be locked)
    // If you want backdrop close, uncomment:
    // modal.querySelector(".smodal-backdrop")?.addEventListener("click", () => {});
}

/**
 * Closes the shop modal UI only.
 * (Backend close + turn advance should happen via shopClose() endpoint.)
 */
function hideShopModal() {
    const modal = document.getElementById("shopModal");
    if (!modal) return;

    SHOP_IS_OPEN = false;

    modal.classList.add("is-hidden");
    modal.setAttribute("aria-hidden", "true");

    // cleanup content to avoid stale offers after refresh
    const offersWrap = document.getElementById("shopOffers");
    if (offersWrap) offersWrap.innerHTML = "";

    const sellWrap = document.getElementById("shopSellList");
    if (sellWrap) sellWrap.innerHTML = "";

    const feedback = document.getElementById("shopFeedback");
    if (feedback) feedback.textContent = "";
}

async function shopBuyCard(cardTypeId) {
    const feedback = document.getElementById("shopFeedback");
    if (feedback) feedback.textContent = "";

    const gameId = getGameIdFromPage();
    if (!gameId) {
        if (feedback) feedback.textContent = "Cannot detect game id.";
        return;
    }

    try {
        const res = await fetch(`/games/${gameId}/shop/buy/`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCSRFToken(),
            },
            body: JSON.stringify({ card_type_id: cardTypeId }),
        });

        const data = await safeJson(res);

        if (!res.ok) {
            if (feedback) feedback.textContent = (data && data.detail) ? data.detail : "Failed to buy.";
            return;
        }

        // Update UI/state
        await applyGameStateUpdate(data);
    } catch (err) {
        console.error(err);
        if (feedback) feedback.textContent = "Network error while buying.";
    }
}

async function shopSellCard(cardInstanceId) {
    const feedback = document.getElementById("shopFeedback");
    if (feedback) feedback.textContent = "";

    const gameId = getGameIdFromPage();
    if (!gameId) {
        if (feedback) feedback.textContent = "Cannot detect game id.";
        return;
    }

    try {
        const res = await fetch(`/games/${gameId}/shop/sell/`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCSRFToken(),
            },
            body: JSON.stringify({ card_instance_id: cardInstanceId }),
        });

        const data = await safeJson(res);

        if (!res.ok) {
            if (feedback) feedback.textContent = (data && data.detail) ? data.detail : "Failed to sell.";
            return;
        }

        await applyGameStateUpdate(data);
    } catch (err) {
        console.error(err);
        if (feedback) feedback.textContent = "Network error while selling.";
    }
}

async function shopClose() {
    const feedback = document.getElementById("shopFeedback");
    if (feedback) feedback.textContent = "";

    const gameId = getGameIdFromPage();
    if (!gameId) {
        if (feedback) feedback.textContent = "Cannot detect game id.";
        return;
    }

    try {
        const res = await fetch(`/games/${gameId}/shop/close/`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCSRFToken(),
            },
            body: JSON.stringify({}),
        });

        const data = await safeJson(res);

        if (!res.ok) {
            if (feedback) feedback.textContent = (data && data.detail) ? data.detail : "Failed to close shop.";
            return;
        }

        await applyGameStateUpdate(data);

        // If state says no pending_shop anymore, hide
        // (applyGameStateUpdate should re-render and hide automatically, but this is safe)
        hideShopModal();
    } catch (err) {
        console.error(err);
        if (feedback) feedback.textContent = "Network error while closing shop.";
    }
}


// -----------------------------
// Draft Mode UI + actions
// -----------------------------

function setDraftModalVisible(visible) {
    const modal = document.getElementById("draftModal");
    if (!modal) return;
    if (visible) {
        modal.classList.remove("is-hidden");
        modal.setAttribute("aria-hidden", "false");
    } else {
        modal.classList.add("is-hidden");
        modal.setAttribute("aria-hidden", "true");
    }
}

function renderDraftUI(state) {
    // state.draft expected from backend to_public_state()
    const draft = state && state.draft ? state.draft : null;

    // If not drafting, hide modal
    if (!draft || !draft.active) {
        setDraftModalVisible(false);
        return;
    }

    setDraftModalVisible(true);

    const sub = document.getElementById("draftSub");
    const choicesEl = document.getElementById("draftChoices");
    const feedbackEl = document.getElementById("draftFeedback");

    if (sub) {
        sub.textContent = `Pick ${Math.min(draft.picks_done + 1, draft.max_picks)} of ${draft.max_picks}`;
    }

    if (feedbackEl) feedbackEl.textContent = "";

    if (!choicesEl) return;

    const options = Array.isArray(draft.options) ? draft.options : [];
    if (options.length === 0) {
        choicesEl.innerHTML = `<div class="qchoice disabled">Waiting for opponents...</div>`;
        return;
    }

    // Build 3 buttons (options are card_type IDs)
    choicesEl.innerHTML = options.map((opt) => `
    <button class="qchoice draft-choice"
            type="button"
            data-card-type="${opt.id}">
        <img class="draft-choice-img" src="${opt.image_url}" alt="">
        <span>${opt.title}</span>
    </button>
    `).join("");

    // Click handlers
    choicesEl.querySelectorAll("button[data-card-type]").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const cardTypeId = btn.getAttribute("data-card-type");
            const gameId = window.GAME_ID;

            // Disable all choices while sending
            choicesEl.querySelectorAll("button").forEach((b) => (b.disabled = true));

            try {
                await draftPick(gameId, cardTypeId);
                // After pick, refresh state immediately so next options show
                if (typeof fetchGameState === "function") {
                    await fetchGameState();
                }
            } catch (err) {
                if (feedbackEl) feedbackEl.textContent = err?.message || "Draft pick failed.";
                // Re-enable choices
                choicesEl.querySelectorAll("button").forEach((b) => (b.disabled = false));
            }
        });
    });
}

async function draftPick(gameId, cardTypeId) {
    const resp = await fetch(`/games/${gameId}/draft/pick/`, {
        method: "POST",
        headers: {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": getCookie("csrftoken") || "",
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ card_type_id: cardTypeId }),
    });

    if (!resp.ok) {
        let msg = `Error: ${resp.status}`;
        try {
            const data = await resp.json();
            if (data && (data.detail || data.error)) msg = data.detail || data.error;
        } catch (_) { }
        throw new Error(msg);
    }

    return resp.json().catch(() => ({}));
}

// ============================
// Duel Modal helpers
// ============================

function showDuelModal() {
    const modal = document.getElementById("duelModal");
    if (!modal) return;

    modal.classList.remove("is-hidden");
    modal.setAttribute("aria-hidden", "false");

    // Optional: prevent background scroll (same UX as other modals)
    document.body.classList.add("modal-open");

    // Clicking the backdrop does NOT close the duel
    // (duel must resolve to avoid turn-skip bugs).
    const backdrop = modal.querySelector(".dmodal-backdrop");
    if (backdrop && !backdrop.dataset.bound) {
        backdrop.dataset.bound = "1";
        backdrop.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            // Do nothing by design.
        });
    }

    // Prevent clicks inside card from bubbling to backdrop
    const card = modal.querySelector(".dmodal-card");
    if (card && !card.dataset.bound) {
        card.dataset.bound = "1";
        card.addEventListener("click", (e) => e.stopPropagation());
    }

    // Esc does NOT close (same reason)
    if (!modal.dataset.escBound) {
        modal.dataset.escBound = "1";
        document.addEventListener("keydown", (e) => {
            const isOpen = !modal.classList.contains("is-hidden");
            if (!isOpen) return;
            if (e.key === "Escape") {
                e.preventDefault();
                e.stopPropagation();
            }
        }, true);
    }
}

function hideDuelModal() {
    const modal = document.getElementById("duelModal");
    if (!modal) return;

    modal.classList.add("is-hidden");
    modal.setAttribute("aria-hidden", "true");

    // Optional: restore scroll
    document.body.classList.remove("modal-open");

    // Clean UI content so stale duel info doesn't flash next time
    const body = document.getElementById("dBody");
    if (body) body.innerHTML = "";

    const feedback = document.getElementById("dFeedback");
    if (feedback) feedback.textContent = "";
}

// Optional convenience: show a message inside duel modal
function setDuelFeedback(msg) {
    const el = document.getElementById("dFeedback");
    if (!el) return;
    el.textContent = msg || "";
}

function renderDuelUI(duel, gameState) {
    const body = document.getElementById("dBody");
    const feedback = document.getElementById("dFeedback");
    if (!body) return;

    body.innerHTML = "";
    if (feedback) feedback.textContent = "";

    const myId = gameState.you_player_id;
    const players = gameState.players || [];
    const getName = (pid) => {
        const p = players.find(x => x.id === pid);
        return p ? p.username : `Player ${pid}`;
    };

    // -------------------------
    // Phase: choose opponent
    // -------------------------
    if (duel.status === "choose_opponent") {
        body.innerHTML = `
            <h4 class="dsection-title">Choose an opponent</h4>
            <div class="dgrid"></div>
        `;
        const grid = body.querySelector(".dgrid");

        players.forEach(p => {
            if (!p.is_alive || p.id === myId) return;
            const btn = document.createElement("button");
            btn.className = "dbtn";
            btn.innerHTML = `<strong>${p.username}</strong><br><small>HP ${p.hp} • Coins ${p.coins}</small>`;
            btn.onclick = async () => {
                try {
                    // UI feedback
                    if (feedback) feedback.textContent = "Selecting opponent...";
                    btn.disabled = true;

                    const res = await fetch(`/games/${gameState.id}/duel/select_opponent/`, {
                        method: "POST",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "X-CSRFToken": getCSRFToken(),
                            "Content-Type": "application/x-www-form-urlencoded",
                        },
                        body: `opponent_id=${encodeURIComponent(p.id)}`
                    });

                    const payload = await safeJson(res);

                    if (!res.ok) {
                        const msg = (payload && (payload.detail || payload.error)) ? (payload.detail || payload.error) : `Error ${res.status}`;
                        if (feedback) feedback.textContent = msg;
                        btn.disabled = false;
                        return;
                    }

                    // Apply new server state immediately (no waiting for poll)
                    await applyGameStateUpdate(payload);

                    // If duel is still pending, re-render duel UI right now
                    const st = payload && payload.game_state ? payload.game_state : null;
                    if (st && st.pending_duel) {
                        showDuelModal();
                        renderDuelUI(st.pending_duel, st);
                    }

                    if (feedback) feedback.textContent = "";
                } catch (e) {
                    console.error(e);
                    if (feedback) feedback.textContent = "Network error while selecting opponent.";
                    btn.disabled = false;
                }
            };

            grid.appendChild(btn);
        });
        return;
    }

    // -------------------------
    // Phase: commit (hidden)
    // -------------------------
    if (duel.status === "commit") {
        body.innerHTML = `
            <h4 class="dsection-title">Choose your action (hidden)</h4>
            <div class="dgrid">
                <button class="dbtn" data-choice="attack">
                    <strong>Attack</strong><br><small>No cost</small>
                </button>
                <button class="dbtn" data-choice="defend">
                    <strong>Defend</strong><br><small>Cost: 1 coin</small>
                </button>
                <button class="dbtn" data-choice="bluff">
                    <strong>Bluff</strong><br><small>Cost: 1 support card</small>
                </button>
            </div>
        `;

        if (duel.you_committed) {
            body.innerHTML += `<p class="qfeedback">Waiting for opponent…</p>`;
            body.querySelectorAll("button").forEach(b => b.disabled = true);
            return;
        }

        body.querySelectorAll("button[data-choice]").forEach(btn => {
            btn.onclick = async () => {
                await fetch(`/games/${gameState.id}/duel/commit/`, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": getCSRFToken(),
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    body: `choice=${btn.dataset.choice}`
                });
            };
        });
        return;
    }

    // -------------------------
    // Phase: predict
    // -------------------------
    if (duel.status === "predict") {
        body.innerHTML = `
            <h4 class="dsection-title">Predict opponent’s choice</h4>
            <div class="dgrid">
                <button class="dbtn" data-pred="attack">Attack</button>
                <button class="dbtn" data-pred="defend">Defend</button>
                <button class="dbtn" data-pred="bluff">Bluff</button>
            </div>
        `;

        if (duel.you_predicted) {
            body.innerHTML += `<p class="qfeedback">Waiting for opponent…</p>`;
            body.querySelectorAll("button").forEach(b => b.disabled = true);
            return;
        }

        body.querySelectorAll("button[data-pred]").forEach(btn => {
            btn.onclick = async () => {
                await fetch(`/games/${gameState.id}/duel/predict/`, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": getCSRFToken(),
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    body: `prediction=${btn.dataset.pred}`
                });
            };
        });
        return;
    }

    // -------------------------
    // Phase: winner chooses reward
    // -------------------------
    if (duel.status === "winner_choice") {
        const isWinner = duel.winner_id === myId;

        body.innerHTML = `
            <h4 class="dsection-title">
                ${isWinner ? "You won! Choose your reward" : "You lost the duel"}
            </h4>
        `;

        if (duel.reveal) {
            body.innerHTML += `
                <div class="dreveal">
                    <div class="drow"><span>${getName(duel.initiator_id)}</span><span>${duel.reveal.initiator_choice}</span></div>
                    <div class="drow"><span>${getName(duel.opponent_id)}</span><span>${duel.reveal.opponent_choice}</span></div>
                </div>
            `;
        }

        if (!isWinner) {
            body.innerHTML += `<p class="qfeedback">Waiting for winner to choose reward…</p>`;
            return;
        }

        body.innerHTML += `
            <div class="dgrid">
                <button class="dbtn" data-act="coins">+3 Coins</button>
                <button class="dbtn" data-act="hp">-1 HP to opponent</button>
                <button class="dbtn" data-act="push_back">Push back 1 tile</button>
                <button class="dbtn" data-act="steal_card">Steal support card</button>
            </div>
        `;

        body.querySelectorAll("button[data-act]").forEach(btn => {
            btn.onclick = async () => {
                await fetch(`/games/${gameState.id}/duel/choose_reward/`, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": getCSRFToken(),
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    body: `action=${btn.dataset.act}`
                });
            };
        });
        return;
    }

    // -------------------------
    // Phase: resolved / draw
    // -------------------------
    if (duel.status === "resolved") {
        body.innerHTML = `
            <h4 class="dsection-title">
                ${duel.is_draw ? "Duel ended in a draw" : "Duel resolved"}
            </h4>
            <p class="qfeedback">Turn continues…</p>
        `;
    }
}

// ---------- UI: board ----------
// Tiles are rendered strictly in ascending position order (0..49),
// and displayed as 1..50 in the index badge.

function updateBoardUI(state) {
    if (!state) return;
    const container = document.getElementById("board-tiles");
    if (!container) return;

    const tilesRaw = Array.isArray(state.tiles) ? state.tiles : [];
    const playersRaw = Array.isArray(state.players) ? state.players : [];

    // FIX: Deduplicate players by ID to prevent visual "4 players" bug
    const seenIds = new Set();
    const players = [];
    for (const p of playersRaw) {
        if (!seenIds.has(p.id)) {
            seenIds.add(p.id);
            players.push(p);
        }
    }

    // Group players by tile position
    const playersByPos = {};
    for (const p of players) {
        const pos = typeof p.position === "number" ? p.position : 0;
        if (!playersByPos[pos]) playersByPos[pos] = [];
        playersByPos[pos].push(p);
    }

    // Ensure stable ordering 0..N by position
    const tiles = tilesRaw.slice().sort((a, b) => {
        const pa = typeof a.position === "number" ? a.position : 0;
        const pb = typeof b.position === "number" ? b.position : 0;
        return pa - pb;
    });

    const html = tiles.map(tile => {
        // ... (keep existing tile rendering logic)
        const pos = typeof tile.position === "number" ? tile.position : 0;
        const tPlayers = playersByPos[pos] || [];
        const hasCurrent = tPlayers.some(p => p.is_current_turn);

        let label = tile.label || "";
        const type = (tile.type || tile.tile_type || "empty").toLowerCase();

        if (!label) {
            switch (type) {
                case "start": label = "Start"; break;
                case "finish": label = "Finish"; break;
                case "trap": label = "Trap"; break;
                case "heal": label = "Heal"; break;
                case "bonus": label = "Bonus"; break;
                case "question": label = "?"; break;
                case "warp": label = "Warp"; break;
                case "mass_warp": label = "Mass Warp"; break;
                case "duel": label = "Duel"; break;
                case "shop": label = "Shop"; break;
                default: label = ""; break;
                case "portal": label = "Portal"; break;
            }
        }

        /* --- BONUS TILE HTML (🎁 + corner badge) --- */
        let labelHtml = escapeHtml(label);

        if (type === "bonus") {
            labelHtml = `<div class="board-tile-symbol">🎁</div>`;
        }
        if (type === "portal") {
            labelHtml = `<div class="board-tile-symbol">🌀</div>`;
        }

        // ... (keep rest of tile map logic)
        const tileClasses = ["board-tile", `board-tile-${type}`];
        if (hasCurrent) tileClasses.push("board-tile-current");

        return `
            <div class="${tileClasses.join(" ")}" data-position="${pos}">
                <div class="board-tile-index">${pos + 1}</div>
                <div class="board-tile-label">${labelHtml}</div>
                <div class="board-tile-players"></div>
                <div class="tile-tokens"></div>
            </div>
        `;
    }).join("");

    container.innerHTML = html || "<div>No tiles.</div>";
}

// ---------- UI: players panel ----------

function updatePlayersUI(state) {
    if (!state) return;

    const listEl = document.getElementById("player-list");
    const countEl = document.getElementById("player-count");

    const playersRaw = Array.isArray(state.players) ? state.players : [];

    // FIX: Deduplicate players here as well for the sidebar list
    const seenIds = new Set();
    const players = [];
    for (const p of playersRaw) {
        if (!seenIds.has(p.id)) {
            seenIds.add(p.id);
            players.push(p);
        }
    }

    if (countEl) {
        const maxPlayers = window.GAME_MAX_PLAYERS || "?";
        countEl.textContent = `${players.length} / ${maxPlayers}`;
    }

    if (!listEl) return;

    const hostUserId = window.GAME_HOST_USER_ID;

    const playersHtml = players.map(p => {
        // ... (keep existing player row rendering)
        const isHost = (hostUserId !== null && p.user_id === hostUserId);
        const isFirstTurnOrder = p.turn_order === 0;

        let rolesHtml = "";
        if (isHost) rolesHtml += '<span class="player-role">Host</span>';
        if (isFirstTurnOrder) rolesHtml += '<span class="player-role player-role-turn">Turn order #1</span>';
        if (p.is_current_turn) rolesHtml += '<span class="player-role player-role-turn">Current turn</span>';
        if (p.is_you) rolesHtml += '<span class="player-role player-role-you">You</span>';

        const statusBadge = p.is_alive
            ? '<span class="badge badge-soft">Alive</span>'
            : '<span class="badge badge-soft badge-soft-danger">Eliminated</span>';

        return `
            <li class="player-row">
                <div class="player-main">
                    <div class="player-avatar">
                        ${escapeHtml(p.username.charAt(0).toUpperCase())}
                    </div>
                    <div class="player-text">
                        <div class="player-name">
                            ${escapeHtml(p.username)}
                            ${rolesHtml}
                        </div>
                        <div class="player-meta">
                            Turn order: ${p.turn_order + 1}
                        </div>
                    </div>
                </div>
                <div class="player-stats">
                    <span class="player-stat">HP: <strong>${p.hp}</strong></span>
                    <span class="player-stat">Coins: <strong>${p.coins}</strong></span>
                    <span class="player-stat">Pos: <strong>${p.position}</strong></span>
                    <span class="player-stat">${statusBadge}</span>
                </div>
            </li>
        `;
    }).join("");

    listEl.innerHTML = playersHtml || "<li>No players.</li>";
}
// ---------- UI: dice / turn ----------

function updateDiceUI(state) {
    const labelEl = document.getElementById("current-turn-label");
    const rollButton = document.getElementById("roll-button");
    const diceText = document.getElementById("dice-text");

    if (!state) return;

    if (state.status !== "active") {
        if (labelEl) labelEl.textContent = "Game is not active.";
        if (rollButton) rollButton.disabled = true;
        return;
    }

    const players = Array.isArray(state.players) ? state.players : [];
    const current = players.find(p => p.is_current_turn);
    const youId = state.you_player_id;
    const isYourTurn = current && current.id === youId;

    if (labelEl) {
        if (current) {
            labelEl.textContent = `Current player: ${current.username}` + (isYourTurn ? " (you)" : "");
        } else {
            labelEl.textContent = "Current player: unknown.";
        }
    }

    if (rollButton) {
        rollButton.disabled = !isYourTurn || !players.some(p => p.is_alive);
    }

    if (state.status === "finished") {
        if (rollButton) rollButton.disabled = true;
        if (labelEl) labelEl.textContent = "Game finished.";
    }

    const diceDisplay = document.getElementById("dice-display");
    if (diceText && (!diceDisplay || !diceDisplay.dataset.hasValue)) {
        const currentName = current && current.username ? current.username : null;
        diceText.textContent = isYourTurn
            ? "It is your turn. Roll the dice."
            : (currentName ? `Waiting for ${currentName} to roll.` : "Waiting for the current player to roll.");
    }
}


// ---------- Support Cards (inventory) ----------

async function useCard(gameId, cardId, targetPlayerId = null) {
    const payload = { card_id: cardId };
    if (targetPlayerId !== null) payload.target_player_id = targetPlayerId;

    const resp = await fetch(`/games/${gameId}/use_card/`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": getCookie("csrftoken") || "",
        },
        body: JSON.stringify(payload),
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        alert(data.detail || `Error ${resp.status}`);
        return;
    }

    const state = data.game_state || data;

    updateBoardUI(state);
    updatePlayersUI(state);
    updateDiceUI(state);
    renderPlayerTokens(state);
    renderQuestionUI(state);
    renderInventoryUI(state);
}

function renderInventoryUI(state) {
    const wrap = document.getElementById("inventory-cards");
    if (!wrap) return;

    const shieldEl = document.getElementById("inv-shield");
    const extraEl = document.getElementById("inv-extra-rolls");

    if (shieldEl) shieldEl.textContent = state.you_shield_points ?? 0;
    if (extraEl) extraEl.textContent = state.you_extra_rolls ?? 0;

    const cards = Array.isArray(state.your_cards) ? state.your_cards : [];

    if (cards.length === 0) {
        wrap.innerHTML = `<div class="muted">No cards</div>`;
        return;
    }

    wrap.innerHTML = cards
        .map(
            (c) => `
      <div class="inv-card">
        <div class="inv-card-title">${escapeHtml(c.name)}</div>
        <div class="inv-card-desc">${escapeHtml(c.description || "")}</div>
        <button class="btn btn-sm btn-primary inv-use-btn"
                data-card-id="${c.id}"
                data-effect="${escapeHtml(c.effect_type || "")}">
          Use
        </button>
      </div>
    `
        )
        .join("");

    wrap.querySelectorAll(".inv-use-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const cardId = btn.getAttribute("data-card-id");
            const effect = btn.getAttribute("data-effect");
            const gameId = window.GAME_ID;

            // swap_position needs target player (adjacent)
            if (effect === "swap_position") {
                const players = Array.isArray(state.players) ? state.players : [];
                const me = players.find((p) => p.is_you);
                if (!me) {
                    alert("Could not identify your player.");
                    return;
                }

                const adjacent = players.filter(
                    (p) =>
                        !p.is_you &&
                        p.is_alive &&
                        (p.position === me.position - 1 || p.position === me.position + 1)
                );

                if (adjacent.length === 0) {
                    alert("No adjacent player to swap with.");
                    return;
                }

                // simplest: swap with first adjacent
                useCard(gameId, cardId, adjacent[0].id);
                return;
            }

            useCard(gameId, cardId);
        });
    });
}

// ---------- fetch state ----------

async function fetchGameState(gameId) {
    try {
        const resp = await fetch(`/games/${gameId}/state/`, {
            headers: { "X-Requested-With": "XMLHttpRequest" }
        });
        if (!resp.ok) return;

        const data = await resp.json();

        updateBoardUI(data);
        updatePlayersUI(data);
        updateDiceUI(data);
        renderPlayerTokens(data);
        renderInventoryUI(data);
        renderQuestionUI(data);
        renderDraftUI(data);


        if (data.pending_duel) {
            showDuelModal();
            // If you have a renderer, call it. If not, skip this line for now.
            if (typeof renderDuelUI === "function") {
                renderDuelUI(data.pending_duel, data);
            }
        } else {
            hideDuelModal();
        }

        if (data.pending_shop) {
            showShopModal(data.pending_shop, data);
        }
        else hideShopModal();

        // NEW: if game finished -> show congrats popup + stop polling
        if (data && (data.status === "finished" || data.has_winner === true)) {
            // show modal (requires the modal HTML + bqOpenFinishModal from earlier)
            bqOpenFinishModal(data);

            // stop polling if you are polling with setInterval
            if (window.gamePoller) {
                clearInterval(window.gamePoller);
                window.gamePoller = null;
            }
        }

    } catch (e) {
        console.error("board state error:", e);
    }
}

// ---------- roll ----------
function startDiceShuffle() {
    const { die } = getDiceEls();
    if (!die) return null;

    let alive = true;
    const interval = setInterval(() => {
        if (!alive) return;
        const v = 1 + Math.floor(Math.random() * 6);
        toggleDiceClasses(die);
        die.dataset.roll = String(v);
    }, 90);

    return () => {
        alive = false;
        clearInterval(interval);
    };
}
async function handleRollClick(e) {
    e.preventDefault();
    const gameId = window.GAME_ID;
    if (!gameId) return;

    const rollButton = document.getElementById("roll-button");
    const diceDisplay = document.getElementById("dice-display");
    const diceText = document.getElementById("dice-text");
    const logEl = document.getElementById("dice-log");

    if (rollButton) rollButton.disabled = true;
    if (diceDisplay) diceDisplay.dataset.hasValue = "1";
    if (diceText) diceText.textContent = "Rolling...";
    const stopShuffle = startDiceShuffle();


    try {
        const resp = await fetch(`/games/${gameId}/roll/`, {
            method: "POST",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": getCookie("csrftoken") || "",
            },
            body: new FormData(),
        });

        if (!resp.ok) {
            let msg = `Error: ${resp.status}`;
            try {
                const errData = await resp.json();
                if (errData.detail) msg = errData.detail;
            } catch (_) { }
            if (diceDisplay) diceDisplay.textContent = msg;
            fetchGameState(gameId);
            if (typeof stopShuffle === "function") stopShuffle();
            return;
        }

        const data = await resp.json();
        const result = data.result || data.action || {};
        const dice = result.dice;
        const move = result.move || {};
        const state = data.game_state;

        if (typeof stopShuffle === "function") stopShuffle();

        if (typeof dice !== "undefined") {
            // animate to the final server value
            animateDieTo(Number(dice));
            if (diceText) diceText.textContent = `You rolled ${dice}.`;
        }

        if (logEl && move) {
            const from = move.from_position;
            const to = move.to_position;
            const tileType = move.landed_tile_type;
            const tileEffect = move.tile_effect || {};

            let text = `Moved from ${from} to ${to}.`;
            if (tileType) text += ` Landed on ${tileType}.`;
            if (tileEffect.hp_delta) {
                text += ` HP ${tileEffect.hp_delta > 0 ? "+" + tileEffect.hp_delta : tileEffect.hp_delta}.`;
            }
            if (tileEffect.coins_delta) {
                text += ` Coins ${tileEffect.coins_delta > 0 ? "+" + tileEffect.coins_delta : tileEffect.coins_delta}.`;
            }
            if (tileEffect.extra && tileEffect.extra.died) text += " You died.";
            if (tileEffect.extra && tileEffect.extra.opponent_died) text += " Opponent died.";
            if (move.teleported) {
                text += " 🌀 Teleported to Start!";
            }
            const p = document.createElement("p");
            p.textContent = text;
            logEl.prepend(p);
        }

        if (state) {
            updateBoardUI(state);
            updatePlayersUI(state);
            updateDiceUI(state);
            renderPlayerTokens(state);
            renderQuestionUI(state);
            renderInventoryUI(state);
        }
    } catch (e) {
        console.error("roll error:", e);
        const diceDisplay = document.getElementById("dice-display");
        if (typeof stopShuffle === "function") stopShuffle();
        if (diceDisplay) diceDisplay.textContent = "Error while rolling.";
    }
}

// ---------- tokens ----------

function getPlayerInitials(player) {
    const name = (player.username || "").trim();
    if (!name) return "?";
    const parts = name.split(/\s+/);
    if (parts.length === 1) {
        return parts[0].substring(0, 2).toUpperCase();
    }
    return (parts[0][0] + parts[1][0]).toUpperCase();
}

function renderPlayerTokens(gameState) {
    if (!gameState || !Array.isArray(gameState.players)) return;

    // FIX: Deduplicate players for token rendering
    const seenIds = new Set();
    const uniquePlayers = [];
    for (const p of gameState.players) {
        if (!seenIds.has(p.id)) {
            seenIds.add(p.id);
            uniquePlayers.push(p);
        }
    }

    // Clear existing tokens
    const tiles = document.querySelectorAll(".board-tile");
    tiles.forEach(tile => {
        const tokenContainer = tile.querySelector(".tile-tokens");
        if (tokenContainer) {
            tokenContainer.innerHTML = "";
        }
    });

    // Build mapping: tileIndex -> [players]
    const playersByTile = {};
    uniquePlayers.forEach(player => {
        const pos = typeof player.position === "number" ? player.position : 0;
        if (!playersByTile[pos]) {
            playersByTile[pos] = [];
        }
        playersByTile[pos].push(player);
    });

    // Render tokens into each tile
    Object.entries(playersByTile).forEach(([tileIndex, players]) => {
        // ... (keep existing token DOM creation)
        const tile = document.querySelector(
            `.board-tile[data-position="${tileIndex}"]`
        );
        if (tile && tile.classList.contains("board-tile-portal")) {
            return;
        }
        if (!tile) return;

        let tokenContainer = tile.querySelector(".tile-tokens");
        if (!tokenContainer) {
            tokenContainer = document.createElement("div");
            tokenContainer.classList.add("tile-tokens");
            tile.appendChild(tokenContainer);
        }

        players.forEach((player, idx) => {
            const token = document.createElement("div");
            token.classList.add("player-token");

            if (gameState.current_player_id &&
                String(gameState.current_player_id) === String(player.id)) {
                token.classList.add("player-token-current");
            }

            token.style.setProperty("--token-index", idx);
            token.textContent = getPlayerInitials(player);
            tokenContainer.appendChild(token);
        });
    });
}


// ---------- init ----------

document.addEventListener("DOMContentLoaded", function () {
    if (typeof window.GAME_ID === "undefined") return;

    fetchGameState(window.GAME_ID);
    window.gamePoller = setInterval(function () {
        fetchGameState(window.GAME_ID);
    }, 2000);

    const rollBtn = document.getElementById("roll-button");
    if (rollBtn) rollBtn.addEventListener("click", handleRollClick);
});
function bqOpenFinishModal(state) {
    const modal = document.getElementById("finishModal");
    const tbody = document.getElementById("finishLeaderboardBody");
    const closeBtn = document.getElementById("finishCloseBtn");
    const backBtn = document.getElementById("backToLobbyBtn");

    if (!modal || !tbody) return;

    // Back button fallback if you prefer JS redirect
    if (backBtn && window.BQ_LOBBY_URL) {
        backBtn.href = window.BQ_LOBBY_URL;
    }

    // Render leaderboard
    tbody.innerHTML = "";

    const lb = (state && state.leaderboard) ? state.leaderboard : [];
    lb.forEach(row => {
        const status = (row.status || "").toLowerCase();
        const pillClass =
            status === "winner" ? "winner" :
                status === "eliminated" ? "eliminated" : "alive";

        const tr = document.createElement("tr");
        if (row.rank === 1 || status === "winner") tr.classList.add("bq-row-winner");

        tr.innerHTML = `
      <td>${row.rank ?? ""}</td>
      <td>${escapeHtml(row.username ?? "")}</td>
      <td>${row.position ?? ""}</td>
      <td>${row.coins ?? ""}</td>
      <td>${row.hp ?? ""}</td>
      <td><span class="bq-pill ${pillClass}">${escapeHtml(row.status ?? "")}</span></td>
    `;

        tbody.appendChild(tr);
    });

    // Show modal
    modal.classList.remove("bq-hidden");
    modal.setAttribute("aria-hidden", "false");

    // Close handlers
    const close = () => {
        modal.classList.add("bq-hidden");
        modal.setAttribute("aria-hidden", "true");
    };

    if (closeBtn) closeBtn.onclick = close;

    // Close when clicking backdrop (not the card)
    modal.onclick = (e) => {
        if (e.target === modal) close();
    };

    // ESC key closes
    document.addEventListener("keydown", function escHandler(ev) {
        if (ev.key === "Escape") {
            close();
            document.removeEventListener("keydown", escHandler);
        }
    });
}

