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
// -----------------------------
// Activity Log (global, via polling diffs)
// -----------------------------
window.BQ_ACTIVITY = window.BQ_ACTIVITY || {
  lastPlayers: new Map(), // playerId -> { position, hp, coins }
  seenKeys: new Set(),    // to prevent duplicates
};

function tileByPosition(state, pos) {
  if (!state || !Array.isArray(state.tiles)) return null;
  // tiles payload includes { position, type, type_display, ... }
  return state.tiles.find(t => t.position === pos) || null;
}

function playerColorClass(player) {
  // stable color by turn order (or fallback by id)
  const idx = (typeof player.turn_order === "number" ? player.turn_order : (player.id || 0)) % 6;
  return `act-p${idx}`;
}

function appendActivityLine({ player, text }) {
  const logEl = document.getElementById("dice-log");
  if (!logEl) return;

  const p = document.createElement("p");
  p.className = "act-line";

  const name = document.createElement("span");
  name.className = `act-name ${playerColorClass(player)}`;
  name.textContent = player.username || "Player";

  const msg = document.createElement("span");
  msg.className = "act-msg";
  msg.textContent = ` ${text}`;

  p.appendChild(name);
  p.appendChild(msg);

  logEl.prepend(p);
}

function updateActivityFromStateDiff(prevState, nextState) {
  if (!nextState || !Array.isArray(nextState.players)) return;

  // If first run, just snapshot (no spam)
  if (!prevState || !Array.isArray(prevState.players)) {
    window.BQ_ACTIVITY.lastPlayers.clear();
    for (const p of nextState.players) {
      window.BQ_ACTIVITY.lastPlayers.set(p.id, {
        position: p.position,
        hp: p.hp,
        coins: p.coins,
      });
    }
    return;
  }

  const prevMap = window.BQ_ACTIVITY.lastPlayers;

  for (const p of nextState.players) {
    const old = prevMap.get(p.id);
    if (!old) continue;

    const moved = old.position !== p.position;
    const hpDelta = (p.hp ?? 0) - (old.hp ?? 0);
    const coinsDelta = (p.coins ?? 0) - (old.coins ?? 0);

    if (!moved && hpDelta === 0 && coinsDelta === 0) continue;

    const landedTile = moved ? tileByPosition(nextState, p.position) : null;

    let text = "";
    if (moved) {
      text = `moved ${old.position} → ${p.position}`;
      if (landedTile) {
        const typeLabel = landedTile.type_display || landedTile.type || "";
        if (typeLabel) text += ` (landed: ${typeLabel})`;
      }
    } else {
      text = `updated stats`;
    }

    if (hpDelta !== 0) text += ` | HP ${hpDelta > 0 ? `+${hpDelta}` : hpDelta}`;
    if (coinsDelta !== 0) text += ` | Coins ${coinsDelta > 0 ? `+${coinsDelta}` : coinsDelta}`;

    // Dedup key so the same diff doesn’t get appended twice
    const key = `${p.id}|${old.position}->${p.position}|hp${hpDelta}|c${coinsDelta}`;
    if (!window.BQ_ACTIVITY.seenKeys.has(key)) {
      window.BQ_ACTIVITY.seenKeys.add(key);
      appendActivityLine({ player: p, text });
    }
  }

  // Update snapshot
  prevMap.clear();
  for (const p of nextState.players) {
    prevMap.set(p.id, {
      position: p.position,
      hp: p.hp,
      coins: p.coins,
    });
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
let questionTimer = null;
let ACTIVE_QUESTION_KEY = null;   // prevents timer reset on polling
let QUESTION_TIMER_RUNNING = false;

function startQuestionTimer(seconds = 5, onTimeout) {
  const timer = document.getElementById("question-timer");
  const bar = document.getElementById("qtimer-bar");
  const text = document.getElementById("qtimer-text");

  if (!timer || !bar || !text) return;

  clearInterval(questionTimer);

  timer.classList.remove("hidden");
  let remaining = seconds;
  text.textContent = remaining;
  bar.style.width = "100%";

  questionTimer = setInterval(() => {
    remaining--;
    text.textContent = remaining;
    bar.style.width = (remaining / seconds) * 100 + "%";

    if (remaining <= 0) {
        clearInterval(questionTimer);

        // keep visible at 0 so UI doesn't "snap shut"
        text.textContent = "0";
        bar.style.width = "0%";

        // run timeout after a short delay (lets UI finish)
        setTimeout(() => {
            if (typeof onTimeout === "function") onTimeout();
    }, 1000);}
  }, 1000);
}
function getQuestionKey(q) {
  if (!q) return null;

  // Prefer an ID from backend if you have it
  if (q.id !== undefined && q.id !== null) return `id:${q.id}`;

  // Otherwise build a best-effort key from stable fields
  const prompt = q.prompt || q.question || "";
  const correct = (q.correct_index !== undefined && q.correct_index !== null) ? q.correct_index : "";
  return `p:${prompt}|c:${correct}`;
}

function stopQuestionTimer() {
  clearInterval(questionTimer);
}

async function submitQuestionTimeout(gameId) {
  const resp = await fetch(`/games/${gameId}/answer_question/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
      "X-CSRFToken": getCookie("csrftoken") || "",
    },
    body: JSON.stringify({ timeout: true }),
  });

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error((data && data.detail) ? data.detail : `Error: ${resp.status}`);
  }
  return data;
}


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
            ACTIVE_QUESTION_KEY = null;
            stopQuestionTimer();
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
                    renderGunUI(data.game_state);
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
    const qKey = getQuestionKey(q);
    const isSameQuestion = (ACTIVE_QUESTION_KEY && qKey && ACTIVE_QUESTION_KEY === qKey);

    if (!isSameQuestion) {
        ACTIVE_QUESTION_KEY = qKey;
        stopQuestionTimer();

        // start only once per question
        startQuestionTimer(5, async () => {
            // timeout submit
            Array.from(choicesWrap.querySelectorAll("button")).forEach(b => (b.disabled = true));
            changeBtn.disabled = true;
            feedback.textContent = "Time is up.";

            try {
            await submitQuestionTimeout(gameId);
            } finally {
            // force resync after timeout resolves
            fetchGameState(gameId);
            }
        });
    }



}


function hideQuestionModal() {
    ACTIVE_QUESTION_KEY = null;
    stopQuestionTimer();
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

function showGunModal(pendingGun, state) {
  const modal = document.getElementById("gunModal");
  if (!modal) return;

  modal.classList.remove("is-hidden");
  modal.setAttribute("aria-hidden", "false");

  const wrap = document.getElementById("gunTargets");
  const fb = document.getElementById("gunFeedback");
  if (fb) fb.textContent = "";

  // ✅ Bind close/cancel EVERY time (or once) BEFORE any early return
  (function bindGunModalButtonsOnce() {
    const x = document.getElementById("gunCloseBtn");
    const c = document.getElementById("gunCancelBtn");

    if (x && !x.dataset.bound) {
      x.dataset.bound = "1";
      x.addEventListener("click", skipGunAndClose);
    }
    if (c && !c.dataset.bound) {
      c.dataset.bound = "1";
      c.addEventListener("click", skipGunAndClose);
    }
  })();

  const targets = (pendingGun && Array.isArray(pendingGun.targets)) ? pendingGun.targets : [];
  if (!wrap) return;

  // ✅ If no targets, still allow Exit/Cancel to work (skipGunAndClose)
  if (!targets.length) {
    wrap.innerHTML = `<div class="muted">No available targets.</div>`;
    return;
  }

  wrap.innerHTML = targets.map(t => `
    <button type="button" class="gun-target" data-gun-target="${t.id}">
      <div class="name">${escapeHtml(t.username)}</div>
      <div class="hp">HP: ${t.hp}</div>
    </button>
  `).join("");

  wrap.querySelectorAll("[data-gun-target]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const gid = getGameIdFromPage();
      const targetId = Number(btn.getAttribute("data-gun-target"));
      try {
        const res = await fetch(`/games/${gid}/gun/attack/`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCSRFToken(),
          },
          body: JSON.stringify({ target_player_id: targetId }),
        });
        const data = await safeJson(res);
        if (!res.ok) {
          if (fb) fb.textContent = (data && data.detail) ? data.detail : "Failed.";
          return;
        }
        await applyGameStateUpdate(data);
      } catch {
        if (fb) fb.textContent = "Network error.";
      }
    });
  });
}
async function skipDuelAndClose() {
  const gid = getGameIdFromPage();

  try {
    const res = await fetch(`/games/${gid}/duel/skip/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken(),
      },
      body: JSON.stringify({}),
    });

    const data = await safeJson(res);
    if (res.ok) {
      await applyGameStateUpdate(data);
      hideDuelModal();
      return;
    }
  } catch (e) {
    // ignore
  }

  hideDuelModal();
}


function hideGunModal() {
  const modal = document.getElementById("gunModal");
  if (!modal) return;
  modal.classList.add("is-hidden");
  modal.setAttribute("aria-hidden", "true");
}

function renderGunUI(state) {
  if (state && state.pending_gun) showGunModal(state.pending_gun, state);
  else hideGunModal();
}
async function skipGunAndClose() {
  const gid = getGameIdFromPage();

  try {
    const res = await fetch(`/games/${gid}/gun/skip/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken(),
      },
      body: JSON.stringify({}),
    });

    const data = await safeJson(res);
    if (res.ok) {
      await applyGameStateUpdate(data); // updates UI + state
      hideGunModal();
      return;
    }
  } catch (e) {
    // ignore
  }

  // fallback (shouldn't happen often)
  hideGunModal();
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
    const headerRight = document.getElementById("dHeaderRight");
    if (headerRight) headerRight.innerHTML = "";

    // -------------------------
    // Phase: choose opponent
    // -------------------------
    if (duel.status === "choose_opponent") {
        body.innerHTML = `
            <h4 class="dsection-title">Choose an opponent</h4>
            <div class="dgrid"></div>
        `;
        const grid = body.querySelector(".dgrid");

        let added = 0;

        players.forEach(p => {
            if (!p.is_alive || p.id === myId) return;
            added++;

            const btn = document.createElement("button");
            btn.className = "dbtn";
            btn.innerHTML = `<strong>${p.username}</strong><br><small>HP ${p.hp} • Coins ${p.coins}</small>`;
            btn.onclick = async () => {
            try {
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

                await applyGameStateUpdate(payload);

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

        // ✅ no available players -> show Exit (skip duel + advance turn)
        if (added === 0) {
            const headerRight = document.getElementById("dHeaderRight");
            if (headerRight) {
            headerRight.innerHTML = `<button type="button" class="gun-x" id="dExitBtn" aria-label="Close">✕</button>`;
            const exitBtn = document.getElementById("dExitBtn");
            if (exitBtn) exitBtn.onclick = skipDuelAndClose;
            }

            body.innerHTML = `
            <h4 class="dsection-title">Duel</h4>
            <p class="qfeedback">No available opponents.</p>
            `;
        }

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

    const playersByPos = {};
    for (const p of players) {
        const pos = typeof p.position === "number" ? p.position : 0;
        if (!playersByPos[pos]) playersByPos[pos] = [];
        playersByPos[pos].push(p);
    }

    const tiles = tilesRaw.slice().sort((a, b) => {
        const pa = typeof a.position === "number" ? a.position : 0;
        const pb = typeof b.position === "number" ? b.position : 0;
        return pa - pb;
    });
    
    const boardLen = Number(state.board_length || tilesRaw.length || 0);
    const lastPos = boardLen > 0 ? (boardLen - 1) : (tilesRaw.length - 1);

    const html = tiles.map(tile => {
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
                case "portal": label = "Portal"; break;
                case "gun": label = "Gun"; break;
                default: label = ""; break;
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
        if (type === "gun") {
            labelHtml = `<div class="board-tile-symbol">🔫</div>`;
        }

        // ... (keep rest of tile map logic)
        const tileClasses = ["board-tile", `board-tile-${type}`];
        if (hasCurrent) tileClasses.push("board-tile-current");
        let indexText = String(pos);
        if (type === "start" || pos === 0) indexText = "S";
        if (type === "finish" || pos === lastPos) indexText = "F";

        return `
            <div class="${tileClasses.join(" ")}" data-position="${pos}">
                <div class="board-tile-index">${indexText}</div>
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
  // RIGHT BOX = Rankings only
  if (!state) return;

  const listEl = document.getElementById("player-list");
  if (!listEl) return;

  const playersRaw = Array.isArray(state.players) ? state.players : [];

  // Deduplicate by id
  const seenIds = new Set();
  const players = [];
  for (const p of playersRaw) {
    if (p && !seenIds.has(p.id)) {
      seenIds.add(p.id);
      players.push(p);
    }
  }

  // Ranking rule: POSITION (front = higher rank)
  // If you want coins/hp-based rank, tell me and I’ll switch the sort.
  const ranked = players
    .slice()
    .sort((a, b) => (b.position ?? 0) - (a.position ?? 0))
    .map((p, idx) => ({ ...p, rank: idx + 1 }));

  const html = ranked
    .map((p) => {
      const r = p.rank; // now always 1..N
      const badgeClass =
        r === 1
          ? "rank-badge gold"
          : r === 2
          ? "rank-badge silver"
          : r === 3
          ? "rank-badge bronze"
          : "rank-badge";

      const name = (p.username ?? "").toString().trim() || "Player";

      return `
        <li class="rank-row">
          <div class="rank-left">
            <div class="${badgeClass}" aria-label="Rank ${r}">${r}</div>
            <div class="rank-name">
              ${escapeHtml(name)}
              ${p.is_you ? '<span class="rank-tag">You</span>' : ""}
              ${p.is_current_turn ? '<span class="rank-tag turn">Turn</span>' : ""}
            </div>
          </div>
        </li>
      `;
    })
    .join("");

  listEl.innerHTML = html || "<li>No players.</li>";
}


function updatePlayerStatusUI(state) {
  if (!state) return;

  const wrap = document.getElementById("player-status-body");
  if (!wrap) return;

  const playersRaw = Array.isArray(state.players) ? state.players : [];

  // Deduplicate by id
  const seenIds = new Set();
  const players = [];
  for (const p of playersRaw) {
    if (p && !seenIds.has(p.id)) {
      seenIds.add(p.id);
      players.push(p);
    }
  }

  // Stable order: turn_order if exists
  players.sort((a, b) => {
    const ta = typeof a.turn_order === "number" ? a.turn_order : 0;
    const tb = typeof b.turn_order === "number" ? b.turn_order : 0;
    return ta - tb;
  });

  const html = players
    .map((p) => {
      const name = (p.username ?? "").toString().trim() || "Player";
      const initial = name.charAt(0).toUpperCase() || "?";

      const hp = typeof p.hp === "number" ? p.hp : 0;
      const coins = typeof p.coins === "number" ? p.coins : 0;
      const pos = typeof p.position === "number" ? p.position : 0;

      const alive = typeof p.is_alive === "boolean" ? p.is_alive : hp > 0;

      return `
        <div class="ps-item">
            <div class="ps-left">
            <div class="ps-avatar">${escapeHtml(initial)}</div>

            <div class="ps-text">
                <div class="ps-name">
                ${escapeHtml(name)}
                ${p.is_you ? '<span class="ps-chip you">You</span>' : ""}
                ${p.is_current_turn ? '<span class="ps-chip turn">Turn</span>' : ""}
                </div>

                <div class="ps-sub">
                <span class="ps-chip ${alive ? "alive" : "dead"}">${alive ? "Alive" : "Dead"}</span>
                <span class="ps-chip">Pos: <strong>${pos}</strong></span>
                </div>
            </div>
            </div>

            <div class="ps-right">
            <div class="ps-stat">
                <div class="ps-stat-label">POS</div>
                <div class="ps-stat-value">${pos}</div>
            </div>

            <div class="ps-stat">
                <div class="ps-stat-label">HP</div>
                <div class="ps-stat-value">${hp}</div>
            </div>

            <div class="ps-stat">
                <div class="ps-stat-label">COINS</div>
                <div class="ps-stat-value">${coins}</div>
            </div>
            </div>
        </div>
        `;

    })
    .join("");

  wrap.innerHTML = html || `<div class="ps-empty">No players.</div>`;
}



// ---------- UI: dice / turn ----------

function updateDiceUI(state) {
    const labelEl = document.getElementById("current-turn-label");
    const rollButton = document.getElementById("roll-button");
    const diceText = document.getElementById("dice-text");

    if (!state) return;

    // ORDERING phase (turn order roll)
    if (state.status === "ordering") {
        const youId = state.you_player_id;
        const ordering = state.ordering || {};
        const pending = Array.isArray(ordering.pending_player_ids) ? ordering.pending_player_ids : [];
        const canRoll = pending.includes(youId);

        if (labelEl) labelEl.textContent = "Rolling for turn order";
        if (rollButton) rollButton.disabled = !canRoll;

        if (diceText) {
            diceText.textContent = canRoll
                ? "Roll to determine turn order."
                : "Waiting for other players to roll...";
        }
        return;
    }

    // default (non-ordering)
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
    renderGunUI(state);
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

            const ahead = players.filter((p) => !p.is_you && p.is_alive && p.position > me.position);

            if (ahead.length === 0) {
                alert("No alive player ahead of you to swap with.");
                return;
            }

            useCard(gameId, cardId);
            return;
            }


            useCard(gameId, cardId);
        });
    });
}

// ---------- fetch state ----------
function showOrderModal() {
    const modal = document.getElementById("orderModal");
    if (!modal) return;
    modal.classList.remove("is-hidden");
    modal.setAttribute("aria-hidden", "false");
}

function hideOrderModal() {
    const modal = document.getElementById("orderModal");
    if (!modal) return;
    modal.classList.add("is-hidden");
    modal.setAttribute("aria-hidden", "true");
}

function computeProvisionalOrder(state) {
    const ordering = state.ordering || {};
    const rh = ordering.roll_history || {};
    const players = Array.isArray(state.players) ? state.players : [];

    // pid -> sequence tuple
    const seqs = {};
    players.forEach(p => {
        const s = rh[String(p.id)];
        seqs[p.id] = Array.isArray(s) ? s.map(x => Number(x)) : [];
    });

    // sort by sequence (lexicographic desc)
    const sorted = [...players].sort((a, b) => {
        const A = seqs[a.id] || [];
        const B = seqs[b.id] || [];
        const L = Math.max(A.length, B.length);
        for (let i = 0; i < L; i++) {
            const av = (A[i] ?? -1);
            const bv = (B[i] ?? -1);
            if (av !== bv) return bv - av;
        }
        return 0;
    });

    return { sorted, seqs };
}

document.addEventListener("click", (e) => {
    if (e.target && e.target.id === "orderCloseBtn") hideOrderModal();
});
document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "orderRollBtn") {
    const gameId = window.GAME_ID;
    handleRollClick(`/games/${gameId}/order_roll/`);
  }
});


function renderOrderModal(state) {
    const listEl = document.getElementById("orderList");
    const youStatusEl = document.getElementById("orderYourStatus");
    if (!listEl || !state) return;

    const ordering = state.ordering || {};
    const pending = Array.isArray(ordering.pending_player_ids) ? ordering.pending_player_ids : [];
    const { sorted, seqs } = computeProvisionalOrder(state);

    // detect ties by exact same seq
    const keyOf = (pid) => JSON.stringify(seqs[pid] || []);
    const counts = {};
    sorted.forEach(p => { counts[keyOf(p.id)] = (counts[keyOf(p.id)] || 0) + 1; });

    listEl.innerHTML = sorted.map((p, idx) => {
        const rolls = seqs[p.id] || [];
        const isPending = pending.includes(p.id);
        const tie = counts[keyOf(p.id)] > 1;

        const rankText = isPending ? "…" : String(idx + 1);
        const rightText = isPending ? "Pending roll" : (tie ? "TIED (re-roll)" : "OK");

        return `
          <div class="order-row">
            <div class="order-left">
              <div class="order-rank">${rankText}</div>
              <div>
                <div><strong>${escapeHtml(p.username)}</strong>${p.is_you ? " (you)" : ""}</div>
                <div class="order-rolls">Rolls: ${rolls.length ? rolls.join(", ") : "-"}</div>
              </div>
            </div>
            <div class="muted">${rightText}</div>
          </div>
        `;
    }).join("");

    const canRoll = pending.includes(state.you_player_id);
    const rollBtn = document.getElementById("orderRollBtn");
    if (rollBtn) {
        rollBtn.disabled = !canRoll;
    }
    if (youStatusEl) {
        youStatusEl.textContent = canRoll ? "Your turn to roll." : "Wait until you are asked to roll.";
    }
}

async function fetchGameState(gameId) {
    try {
        const resp = await fetch(`/games/${gameId}/state/`, {
            headers: { "X-Requested-With": "XMLHttpRequest" }
        });
        if (!resp.ok) return;

        const data = await resp.json();

        updateActivityFromStateDiff(window.GAME_STATE || null, data);
        window.GAME_STATE = data; 
        
        if (data.status === "ordering") {
            showOrderModal();
            renderOrderModal(data);
        } else {
            hideOrderModal();
        }

        updateBoardUI(data);
        updatePlayersUI(data);
        updatePlayerStatusUI(data);
        updateDiceUI(data);
        renderPlayerTokens(data);
        renderInventoryUI(data);
        renderQuestionUI(data);
        renderDraftUI(data);
        renderGunUI(data);

        const pc = document.getElementById("player-count");
        if (pc) pc.textContent = `${(data.players || []).length} / ${window.GAME_MAX_PLAYERS || ""}`;


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
async function handleRollClick(arg) {
    // arg can be an Event OR a URL string
    if (arg && typeof arg.preventDefault === "function") arg.preventDefault();

    const gameId = window.GAME_ID;
    if (!gameId) return;

    const rollButton = document.getElementById("roll-button");
    const orderRollBtn = document.getElementById("orderRollBtn");
    const diceDisplay = document.getElementById("dice-display");
    const diceText = document.getElementById("dice-text");

    const boardDie = document.getElementById("bq-die-1");
    const orderDie = document.getElementById("orderDie");

    // disable both buttons (sidebar + modal)
    if (rollButton) rollButton.disabled = true;
    if (orderRollBtn) orderRollBtn.disabled = true;

    if (diceDisplay) diceDisplay.dataset.hasValue = "1";
    if (diceText) diceText.textContent = "Rolling...";

    // start shuffle animation for BOTH dice
    const startShuffleFor = (dieEl) => {
        if (!dieEl) return null;
        let alive = true;
        const interval = setInterval(() => {
            if (!alive) return;
            const v = 1 + Math.floor(Math.random() * 6);
            toggleDiceClasses(dieEl);
            dieEl.dataset.roll = String(v);
        }, 90);

        return () => {
            alive = false;
            clearInterval(interval);
        };
    };

    const stopShuffleBoard = startShuffleFor(boardDie);
    const stopShuffleOrder = startShuffleFor(orderDie);

    try {
        const urlOverride = (typeof arg === "string") ? arg : null;
        const isOrdering = window.GAME_STATE && window.GAME_STATE.status === "ordering";
        const url = urlOverride || (isOrdering ? `/games/${gameId}/order_roll/` : `/games/${gameId}/roll/`);

        const resp = await fetch(url, {
            method: "POST",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": getCookie("csrftoken") || "",
            },
            body: new FormData(),
        });

        const data = await safeJson(resp);

        if (!resp.ok) {
            const msg = (data && data.detail) ? data.detail : `Error: ${resp.status}`;
            if (diceText) diceText.textContent = msg;

            if (typeof stopShuffleBoard === "function") stopShuffleBoard();
            if (typeof stopShuffleOrder === "function") stopShuffleOrder();

            // re-poll to restore correct enabled/disabled states
            fetchGameState(gameId);
            return;
        }

        const result = (data && (data.result || data.action)) || {};
        const dice = Number(result.dice);
        const state = data && (data.game_state || data);

        if (typeof stopShuffleBoard === "function") stopShuffleBoard();
        if (typeof stopShuffleOrder === "function") stopShuffleOrder();

        if (!Number.isNaN(dice)) {
            // animate both dice to final value
            if (boardDie) {
                toggleDiceClasses(boardDie);
                boardDie.dataset.roll = String(dice);
            }
            if (orderDie) {
                toggleDiceClasses(orderDie);
                orderDie.dataset.roll = String(dice);
            }
            if (diceText) diceText.textContent = `You rolled ${dice}.`;
        }

        if (state) {
            window.GAME_STATE = state;

            updateBoardUI(state);
            updatePlayersUI(state);
            updateDiceUI(state);
            renderPlayerTokens(state);
            renderInventoryUI(state);
            renderQuestionUI(state);
            renderDraftUI(state);
            renderGunUI(state);

            if (state.status === "ordering") {
                showOrderModal();
                renderOrderModal(state);
            }
        }
    } catch (e) {
        console.error(e);

        if (typeof stopShuffleBoard === "function") stopShuffleBoard();
        if (typeof stopShuffleOrder === "function") stopShuffleOrder();

        if (diceText) diceText.textContent = "Error while rolling.";
        fetchGameState(gameId);
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
// ============================
// GAME CHAT (polling + send)
// ============================

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

function escapeHtml(str) {
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

    row.innerHTML = `<div class="chat-text">${escapeHtml(m.message)}</div>`;
    box.appendChild(row);
  }

  if (liveCount) liveCount.textContent = String(messages.length);
  chatScrollToBottom();
}

async function fetchChat(gameId) {
  const res = await fetch(`/games/${gameId}/chat/messages/`, {
    headers: { "X-Requested-With": "XMLHttpRequest" },
  });
  const data = await res.json().catch(() => null);
  if (!res.ok || !data) return;

  const messages = Array.isArray(data.messages) ? data.messages : [];
  renderChatMessages(messages);
}

function getCSRFToken() {
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
      "X-CSRFToken": getCSRFToken(),
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

function initChat() {
  const gameId = window.GAME_ID;
  const { input, sendBtn, form } = getChatEls();
  if (!gameId || !input || !sendBtn || !form) return;

  // initial load
  fetchChat(gameId);

  // polling
  if (chatPoller) clearInterval(chatPoller);
  chatPoller = setInterval(() => fetchChat(gameId), CHAT_POLL_MS);

  // input enable/disable
  input.addEventListener("input", setSendEnabled);

  // submit
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

  // Enter => send (oddiy input bo‘lgani uchun)
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  // initial state
  setSendEnabled();
}




// ---------- init ----------

// document.addEventListener("DOMContentLoaded", function () {
//     if (typeof window.GAME_ID === "undefined") return;
//
//     fetchGameState(window.GAME_ID);
//     window.gamePoller = setInterval(function () {
//         fetchGameState(window.GAME_ID);
//     }, 2000);
//
//     const rollBtn = document.getElementById("roll-button");
//     if (rollBtn) rollBtn.addEventListener("click", handleRollClick);
//     initChat();
// });
document.addEventListener("DOMContentLoaded", function () {
  const gid = getGameIdFromPage();
  if (!gid) return;

  window.GAME_ID = gid;

  fetchGameState(gid);
  window.gamePoller = setInterval(() => fetchGameState(gid), 2000);

  const rollBtn = document.getElementById("roll-button");
  if (rollBtn) rollBtn.addEventListener("click", handleRollClick);

  initChat(); // ✅ shu kerak
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



