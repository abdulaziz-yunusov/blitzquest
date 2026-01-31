/**
 * =========================================================================
 * CARD DUEL GAME LOGIC
 * =========================================================================
 * Handles frontend logic for the Card Duel game mode:
 * - State polling and updates
 * - Card interaction/playing
 * - Draft selection mechanics
 * - UI rendering (Hand, Opponent, Statuses)
 */

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

async function safeJson(resp) {
  try { return await resp.json(); } catch (_) { return null; }
}

/**
 * =========================================================================
 * RENDER HELPERS
 * =========================================================================
 */

function cardBackUrl() {
  return window.CD_BACK_URL || ((window.STATIC_URL || "/static/") + "images/CardDuelCards/back.png");
}

/**
 * Maps a card code to its corresponding asset filename.
 * Used as a fallback if the image URL is not provided by the backend.
 */
function codeToImageName(code) {
  if (!code) return "Strike.png";

  const c = code.toUpperCase();

  // Buffs & Effects
  if (c.includes("HEAL")) return "RestoreHp.png";
  if (c.includes("SHIELD")) return "IronSkin.png";
  if (c.includes("REGEN")) return "RegenBrew.png";
  if (c.includes("FOCUS")) return "BattleFocus.png";
  if (c.includes("BLESS")) return "PurifyAura.png";

  // Debuffs & Attacks
  if (c.includes("POISON") || c.includes("VENOM")) return "PoisonNeedle.png";
  if (c.includes("BURN") || c.includes("FLAME")) return "BurningMark.png";
  if (c.includes("WEAKEN") || c.includes("CRIPPLE")) return "WeakenCurse.png";
  if (c.includes("VULNERABLE") || c.includes("SUNDER")) return "StunShock.png";
  if (c.includes("SILENCE")) return "SilenceSeal.png";

  // Action Cards
  if (c.includes("STRIKE")) return "Strike.png";
  if (c.includes("PIERCE")) return "GambleCoin.png";
  if (c.includes("TACTICAL")) return "CardCycle.png";
  if (c.includes("DRAW") || c.includes("ADRENALINE")) return "Adrenaline.png";
  if (c.includes("CLEANSE")) return "AntidoteKit.png";

  return "Strike.png"; // Default fallback
}

function cardImageUrlByCode(code) {
  const base = (window.STATIC_URL || "/static/") + "images/CardDuelCards/";
  return base + codeToImageName(code);
}

/**
 * Toggles the visibility of the draft selection modal.
 * Manages ARIA attributes for accessibility.
 */
function setDraftModalVisible(visible) {
  const modal = document.getElementById("draftModal");
  if (!modal) return;

  modal.hidden = !visible;

  if (visible) {
    modal.classList.remove("is-hidden");
    modal.setAttribute("aria-hidden", "false");
  } else {
    modal.classList.add("is-hidden");
    modal.setAttribute("aria-hidden", "true");
  }
}

/**
 * Submits a draft pick to the backend.
 * @param {string} gameId - The ID of the current game.
 * @param {string} code - The code of the selected card.
 */
async function cardDuelPick(gameId, code) {
  const resp = await fetch(`/games/${gameId}/card-duel/pick/`, {
    method: "POST",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
      "X-CSRFToken": getCookie("csrftoken") || "",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ code }),
  });

  const data = await safeJson(resp);
  if (!resp.ok) {
    throw new Error(data?.detail || data?.error || `Error ${resp.status}`);
  }
  return data;
}

/**
 * Renders the draft UI if a pick is required.
 * Hides the modal if drafting is complete.
 */
function renderCardDuelPickUI(state) {
  let pick = null;

  if (state?.card_duel?.pick) {
    pick = state.card_duel.pick;
  } else if (state?.card_duel_pick) {
    pick = state.card_duel_pick;
  }

  const maxPicks = pick.max_picks || 5;

  // Close if no picks needed or exceeded limit
  if ((pick.picks_done || 0) >= maxPicks) {
    setDraftModalVisible(false);
    return;
  }

  const done = Number(pick.picks_done || 0);
  const max = Number(pick.max_picks || 0);

  if (max > 0 && done >= max) {
    setDraftModalVisible(false);
    return;
  }

  // Show draft modal
  setDraftModalVisible(true);

  const sub = document.getElementById("draftSub");
  const choicesEl = document.getElementById("draftChoices");
  const feedbackEl = document.getElementById("draftFeedback");


  if (sub) sub.textContent = `Pick ${Math.min((pick.picks_done || 0) + 1, maxPicks)} of ${maxPicks}`;
  if (feedbackEl) feedbackEl.textContent = "";

  if (!choicesEl) return;

  const options = Array.isArray(pick.options) ? pick.options : [];
  if (!options.length) {
    choicesEl.innerHTML = `<div class="qchoice disabled">Waiting…</div>`;
    return;
  }

  // Render choice buttons
  choicesEl.innerHTML = options.map((opt) => {
    // Use backend image URL if available, otherwise fallback
    const imgSrc = opt.image_url ? opt.image_url : cardImageUrlByCode(opt.code);
    return `
      <button class="qchoice draft-choice" type="button" data-code="${escapeHtml(opt.code)}">
        <img class="draft-choice-img" src="${escapeHtml(imgSrc)}" alt="${escapeHtml(opt.title)}">
        <span>${escapeHtml(opt.title)}</span>
      </button>
    `;
  }).join("");


  // Attach click handlers
  choicesEl.querySelectorAll("button[data-code]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const code = btn.getAttribute("data-code");
      const gameId = window.GAME_ID;

      // Disable buttons to prevent spamming
      choicesEl.querySelectorAll("button").forEach(b => (b.disabled = true));

      try {
        const resp = await cardDuelPick(gameId, code);

        // Immediate update if new state provided
        if (resp && resp.game_state) {
          renderCardDuelPickUI(resp.game_state);
          renderCardDuelUI(resp.game_state);
          return;
        }

        // Fallback polling refresh
        if (typeof fetchCardDuelState === "function") {
          await fetchCardDuelState(gameId);
        } else if (typeof fetchGameState === "function") {
          await fetchGameState(gameId);
        }

      } catch (err) {
        if (feedbackEl) feedbackEl.textContent = err?.message || "Pick failed.";
        choicesEl.querySelectorAll("button").forEach(b => (b.disabled = false));
      }
    });
  });
}


function renderStatuses(el, statuses) {
  if (!el) return;
  const arr = Array.isArray(statuses) ? statuses : [];
  if (!arr.length) {
    el.innerHTML = `<div class="muted">No effects</div>`;
    return;
  }
  el.innerHTML = arr.map(s => {
    const name = escapeHtml(s.name || s.code || s.type || "Effect");
    const turns = (typeof s.turns_left === "number") ? ` (${s.turns_left})` : "";
    const stacks = (s.stacks && s.stacks > 1) ? ` x${s.stacks}` : "";
    return `<span class="ps-chip">${name}${stacks}${turns}</span>`;
  }).join(" ");
}

/**
 * Renders the opponent's hand as card backs.
 */
function renderOpponentHand(count) {
  const wrap = document.getElementById("cd-opp-hand-cards");
  if (!wrap) return;

  const n = Number(count || 0);
  const backSrc = cardBackUrl();

  wrap.setAttribute("data-rendered", `n=${n}`);

  if (n <= 0) {
    wrap.innerHTML = "";
    return;
  }

  wrap.innerHTML = Array.from({ length: n }).map(() => `
    <div class="cd-card cd-card--back">
      <img src="${backSrc}" alt="Card back">
    </div>
  `).join("");
}

function renderLastPlayed(slotId, cardOrCode) {
  const el = document.getElementById(slotId);
  if (!el) return;

  if (!cardOrCode) {
    el.innerHTML = `<div class="muted">No card</div>`;
    return;
  }

  let code = null;
  let imgSrc = null;
  let title = null;

  if (typeof cardOrCode === "string") {
    code = cardOrCode;
    imgSrc = cardImageUrlByCode(code);
    title = code;
  } else {
    code = cardOrCode.code;
    imgSrc = cardOrCode.image_url ? cardOrCode.image_url : cardImageUrlByCode(code);
    title = cardOrCode.title || code;
  }

  if (!code) {
    el.innerHTML = `<div class="muted">No card</div>`;
    return;
  }

  el.innerHTML = `
    <div class="cd-card cd-card--played">
      <img src="${escapeHtml(imgSrc)}" alt="${escapeHtml(title)}">
      <div class="cd-card-title">${escapeHtml(title)}</div>
    </div>
  `;
}

/**
 * Renders the player's active hand.
 * Handles card playing interactions.
 */
function renderHand(hand) {
  const wrap = document.getElementById("cd-hand");
  if (!wrap) return;

  const cards = Array.isArray(hand) ? hand : [];
  if (!cards.length) {
    wrap.innerHTML = `<div class="muted">No cards in hand.</div>`;
    return;
  }

  wrap.innerHTML = cards.map(c => {
    const code = c.code;
    const imgSrc = c.image_url ? c.image_url : cardImageUrlByCode(code);

    return `
      <div class="cd-card" data-card-code="${escapeHtml(code)}">
        <img src="${escapeHtml(imgSrc)}" alt="${escapeHtml(code)}">
      </div>
    `;
  }).join("");
  wrap.classList.toggle("is-collapsed", cards.length > 4);

  // Card Play Handler
  wrap.querySelectorAll(".cd-card[data-card-code]").forEach(card => {
    card.addEventListener("click", async () => {
      if (wrap.dataset.processing === "true") return; // Debounce
      const cardCode = card.getAttribute("data-card-code");
      if (!cardCode) return;

      wrap.dataset.processing = "true";
      card.style.opacity = "0.5";
      card.style.cursor = "wait";

      try {
        const data = await playCard(window.GAME_ID, cardCode);
        if (data && data.game_state) {
          renderCardDuelPickUI(data.game_state);
          renderCardDuelUI(data.game_state);
        }
      } catch (e) {
        console.error(e);
        const fb = document.getElementById("cd-feedback");
        if (fb) fb.textContent = e.message;
        // Sync state on failure
        await fetchCardDuelState(window.GAME_ID);
      } finally {
        wrap.dataset.processing = "false";
        card.style.opacity = "";
        card.style.cursor = "";
      }
    });
  });
}


/**
 * Updates the entire Card Duel UI based on the new game state.
 * @param {object} state - The complete game state object.
 */
function renderCardDuelUI(state) {
  // Extract Card Duel specific state
  const cd = state && (state.card_duel || state.pending_card_duel || state.cardDuel);
  if (!cd) return;

  const you = cd.you || {};
  const opp = cd.opponent || {};

  const setText = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = (v === null || v === undefined) ? "?" : String(v);
  };

  // Render Player Stats
  setText("cd-you-hp", you.hp);
  setText("cd-you-shield", you.shield);
  setText("cd-you-deck", you.deck_count);

  // Render Player Hand
  if (Array.isArray(you.hand)) {
    renderHand(you.hand);
    setText("cd-you-hand", you.hand.length);
  } else {
    setText("cd-you-hand", you.hand_count);
  }

  // Render Opponent Stats
  setText("cd-opp-hp", opp.hp);
  setText("cd-opp-shield", opp.shield);
  setText("cd-opp-deck", opp.deck_count);
  setText("cd-opp-hand", opp.hand_count);
  console.log("[CD] opp.hand_count =", opp.hand_count, "wrap=", document.getElementById("cd-opp-hand-cards"));
  renderOpponentHand(opp.hand_count);


  const isValidCardParam = (p) => p && (typeof p === "string" || p.code);

  // Cache last played card to prevent flickering during empty polls
  let youLastParam = (you.last_played)
    ? you.last_played
    : (you.turn_flags && you.turn_flags.last_played ? you.turn_flags.last_played : null);

  if (isValidCardParam(youLastParam)) {
    window._cdCacheYou = youLastParam;
  } else if (window._cdCacheYou) {
    youLastParam = window._cdCacheYou;
  }

  let oppLastParam = (opp && opp.last_played)
    ? opp.last_played
    : (opp && opp.turn_flags && opp.turn_flags.last_played ? opp.turn_flags.last_played : null);

  if (isValidCardParam(oppLastParam)) {
    window._cdCacheOpp = oppLastParam;
  } else if (window._cdCacheOpp) {
    oppLastParam = window._cdCacheOpp;
  }

  renderLastPlayed("cd-last-played-you", youLastParam);
  renderLastPlayed("cd-last-played-opp", oppLastParam);

  // Turn Information
  const labelEl = document.getElementById("current-turn-label");
  const hintEl = document.getElementById("cd-turn-hint");
  const players = Array.isArray(state.players) ? state.players : [];

  // Determine current turn
  let currentId = state.current_player_id || (cd.current_turn_player_id);
  const current = players.find(p => p.id === currentId);
  const youId = state.you_player_id || (you.player_id);
  const isYourTurn = (currentId === youId);

  if (labelEl) {
    labelEl.textContent = current
      ? `Current player: ${current.username}` + (isYourTurn ? " (you)" : "")
      : "Current player: unknown.";
  }

  if (hintEl) {
    const flags = cd.turn_flags || {};
    const actionUsed = !!flags.action_used;
    const bonusUsed = !!flags.bonus_used;

    hintEl.textContent = isYourTurn
      ? `Your turn. Action used: ${actionUsed ? "Yes" : "No"}, Bonus used: ${bonusUsed ? "Yes" : "No"}`
      : "Waiting for opponent…";
  }

  // Manage End Turn Button
  const endBtn = document.getElementById("cd-endturn-btn");
  if (endBtn) {
    endBtn.disabled = !isYourTurn || state.status !== "active";
  }
}

/**
 * =========================================================================
 * API CALLS
 * =========================================================================
 */

async function fetchCardDuelState(gameId) {
  const resp = await fetch(`/games/${gameId}/state/`, {
    headers: { "X-Requested-With": "XMLHttpRequest" }
  });
  if (!resp.ok) return;

  const data = await resp.json();

  // Update global UI components if available
  if (typeof window.updatePlayersUI === "function") window.updatePlayersUI(data);
  if (typeof window.updatePlayerStatusUI === "function") window.updatePlayerStatusUI(data);

  renderCardDuelUI(data);
  renderCardDuelPickUI(data);

  // Check for game completion
  if (data && (data.status === "finished" || data.has_winner === true)) {
    if (window.__cardDuelInterval) {
      clearInterval(window.__cardDuelInterval);
      window.__cardDuelInterval = null;
    }
    bqOpenFinishModal(data);
  }
}

async function playCard(gameId, cardCode) {
  const resp = await fetch(`/games/${gameId}/card-duel/play-card/`, {
    method: "POST",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
      "X-CSRFToken": getCookie("csrftoken") || "",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ card_code: cardCode }),
  });

  const data = await safeJson(resp);
  if (!resp.ok) {
    const msg = data?.detail || data?.error || `Error ${resp.status}`;
    throw new Error(msg);
  }
  return data;
}


async function endTurn(gameId) {
  const resp = await fetch(`/games/${gameId}/card-duel/end-turn/`, {
    method: "POST",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
      "X-CSRFToken": getCookie("csrftoken") || "",
    },
  });

  const data = await safeJson(resp);
  if (!resp.ok) {
    const msg = data?.detail || data?.error || `Error ${resp.status}`;
    throw new Error(msg);
  }
  return data;
}

function bqOpenFinishModal(state) {
  const modal = document.getElementById("finishModal");
  const tbody = document.getElementById("finishLeaderboardBody");
  const closeBtn = document.getElementById("finishCloseBtn");
  const backBtn = document.getElementById("backToLobbyBtn");

  if (!modal || !tbody) return;

  // Render leaderboard
  tbody.innerHTML = "";
  const lb = (state && state.leaderboard) ? state.leaderboard : [];

  const rowsToRender = lb;

  rowsToRender.forEach(row => {
    const status = (row.status || "").toLowerCase();
    let pillClass = "eliminated";
    if (status === "winner") pillClass = "winner";
    else if (status === "alive") pillClass = "alive";

    let statusStyle = "";
    if (status === "alive") {
      statusStyle = "border-color: rgba(34, 197, 94, 1.0);"; // Green border
    }

    const tr = document.createElement("tr");
    if (row.rank === 1 || status === "winner") tr.classList.add("bq-row-winner");

    tr.innerHTML = `
          <td>${row.rank ?? ""}</td>
          <td>${escapeHtml(row.username ?? "")}</td>
          <td>${row.hp ?? "-"}</td>
          <td>${row.shield ?? "-"}</td>
          <td>${row.deck_count ?? "-"}</td>
          <td>${row.hand_count ?? "-"}</td>
          <td><span class="bq-pill ${pillClass}" style="${statusStyle}">${escapeHtml(row.status ?? "")}</span></td>
        `;
    tbody.appendChild(tr);
  });

  // Show modal
  modal.classList.remove("is-hidden");
  modal.classList.remove("bq-hidden");
  modal.setAttribute("aria-hidden", "false");

  const closeCtx = () => {
    modal.classList.add("is-hidden");
    modal.setAttribute("aria-hidden", "true");
  };

  if (closeBtn) {
    closeBtn.onclick = closeCtx;
  }
}

/**
 * =========================================================================
 * INITIALIZATION
 * =========================================================================
 */

document.addEventListener("DOMContentLoaded", () => {
  // Signal to game_state.js that we're handling polling
  window.__cardDuelHandlesPolling = true;

  const gameId = window.GAME_ID;
  if (!gameId) return;

  // Clear sticky caches on load
  window._cdCacheYou = null;
  window._cdCacheOpp = null;

  const rollBtn = document.getElementById("roll-button");
  if (rollBtn) rollBtn.disabled = true;

  const endBtn = document.getElementById("cd-endturn-btn");
  if (endBtn) {
    endBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      endBtn.disabled = true;
      const feedback = document.getElementById("cd-feedback");
      if (feedback) feedback.textContent = "";

      try {
        await endTurn(gameId);
      } catch (err) {
        if (feedback) feedback.textContent = err?.message || "Failed to end turn.";
        // re-enable if failed
        endBtn.disabled = false;
      } finally {
        fetchCardDuelState(gameId);
      }
    });
  }

  fetchCardDuelState(gameId);
  window.__cardDuelInterval = setInterval(() => fetchCardDuelState(gameId), 1500);

  if (typeof window.initChat === "function") {
    window.initChat();
  }
});