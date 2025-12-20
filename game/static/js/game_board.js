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
            case "start":     label = "Start"; break;
            case "finish":    label = "Finish"; break;
            case "trap":      label = "Trap"; break;
            case "heal":      label = "Heal"; break;
            case "bonus":     label = "Bonus"; break;
            case "question":  label = "?"; break;
            case "warp":      label = "Warp"; break;
            case "mass_warp": label = "Mass Warp"; break;
            case "duel":      label = "Duel"; break;
            case "shop":      label = "Shop"; break;
            default:          label = ""; break;
        }
        }

        /* --- BONUS TILE HTML (🎁 + corner badge) --- */
        let labelHtml = escapeHtml(label);

        if (type === "bonus") {
            labelHtml = `<div class="board-tile-symbol">🎁</div>`;
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
    const diceDisplay = document.getElementById("dice-display");

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

    if (diceDisplay && !diceDisplay.dataset.hasValue) {
        const currentName = current && current.username ? current.username : null;
        diceDisplay.textContent = isYourTurn
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

async function handleRollClick(e) {
    e.preventDefault();
    const gameId = window.GAME_ID;
    if (!gameId) return;

    const rollButton = document.getElementById("roll-button");
    const diceDisplay = document.getElementById("dice-display");
    const logEl = document.getElementById("dice-log");

    if (rollButton) rollButton.disabled = true;
    if (diceDisplay) {
        diceDisplay.textContent = "Rolling.";
        diceDisplay.dataset.hasValue = "1";
    }

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
            } catch (_) {}
            if (diceDisplay) diceDisplay.textContent = msg;
            fetchGameState(gameId);
            return;
        }

        const data = await resp.json();
        const result = data.result || data.action || {};
        const dice = result.dice;
        const move = result.move || {};
        const state = data.game_state;

        if (diceDisplay && typeof dice !== "undefined") {
            diceDisplay.textContent = `You rolled ${dice}.`;
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
    window.__boardInterval = setInterval(function () {
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

