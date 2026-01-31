/**
 * =========================================================================
 * GAME STATE MANAGEMENT
 * =========================================================================
 * Handles the core game loop for board game mode:
 * - Fetches and syncs game state (polling).
 * - Updates the game board, player list, and dice UI.
 * - Handles the "Roll Dice" action.
 */

// -------------------------------------------------------------------------
// HELPER FUNCTIONS
// -------------------------------------------------------------------------

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

// -------------------------------------------------------------------------
// UI: BOARD RENDERING
// -------------------------------------------------------------------------

/**
 * Renders the visual board tiles and player tokens.
 * @param {object} state - The game state containing tile and player data.
 */
function updateBoardUI(state) {
    if (!state) return;

    const container = document.getElementById("board-tiles");
    if (!container) return;

    const tiles = Array.isArray(state.tiles) ? state.tiles : [];
    const players = Array.isArray(state.players) ? state.players : [];

    // Map players by position for faster lookup
    const playersByPos = {};
    for (const p of players) {
        const pos = p.position || 0;
        if (!playersByPos[pos]) {
            playersByPos[pos] = [];
        }
        playersByPos[pos].push(p);
    }

    // Generate HTML for each tile
    const tilesHtml = tiles
        .map((tile) => {
            const tPlayers = playersByPos[tile.position] || [];

            const hasCurrent = tPlayers.some(p => p.is_current_turn);

            // Determine label based on tile type if not explicitly provided
            let label = tile.label || "";
            if (!label) {
                switch (tile.type) {
                    case "start": label = "S"; break;
                    case "finish": label = "F"; break;
                    case "trap": label = "Trap"; break;
                    case "heal": label = "Heal"; break;
                    case "bonus": label = "Bonus"; break;
                    case "question": label = "?"; break;
                    case "warp": label = "Warp"; break;
                    case "mass_warp": label = "Mass"; break;
                    case "duel": label = "Duel"; break;
                    case "shop": label = "Shop"; break;
                    case "gun": label = "Gun"; break;
                    case "empty":
                    default: label = ""; break;
                }
            }

            // Render player tokens on this tile
            const playersHtml = tPlayers
                .map((p) => {
                    const classes = ["player-token"];
                    if (p.is_you) classes.push("player-token-you");
                    if (p.is_current_turn) classes.push("player-token-current");
                    return `
                        <div class="${classes.join(" ")}" title="${escapeHtml(p.username)}">
                            ${escapeHtml(p.username.charAt(0).toUpperCase())}
                        </div>
                    `;
                })
                .join("");

            const tileClasses = ["board-tile", `board-tile-${tile.type}`];
            if (hasCurrent) tileClasses.push("board-tile-current");

            return `
                <div class="${tileClasses.join(" ")}" data-position="${tile.position}">
                    <div class="board-tile-index">${tile.position}</div>
                    <div class="board-tile-label">${escapeHtml(label)}</div>
                    <div class="board-tile-players">
                        ${playersHtml}
                    </div>
                </div>
            `;
        })
        .join("");

    container.innerHTML = tilesHtml || "<p>No board generated yet.</p>";
}

// -------------------------------------------------------------------------
// UI: PLAYERS PANEL
// -------------------------------------------------------------------------

/**
 * Updates the sidebar player list with stats (HP, Coins/Shield, Hand, etc.).
 * Adapts internal layout based on whether it is a Card Duel or Standard Game.
 */
function updatePlayersUI(state) {
    if (!state) return;

    const listEl = document.getElementById("player-list");
    const countEl = document.getElementById("player-count");

    const players = Array.isArray(state.players) ? state.players : [];

    if (countEl) {
        const maxPlayers = window.GAME_MAX_PLAYERS || "?";
        countEl.textContent = `${players.length} / ${maxPlayers}`;
    }

    if (!listEl) return;

    const hostUserId = window.GAME_HOST_USER_ID;

    // Detect Card Duel Mode
    const cd = state && (state.card_duel || state.pending_card_duel || state.cardDuel);
    const isCardDuel = !!cd;

    // Identify 'Your' Player ID
    const youPlayerId = state.you_player_id || (cd && cd.you && cd.you.player_id);

    const playersHtml = players
        .map((p) => {
            // const isHost = (hostUserId !== null && p.user_id === hostUserId);
            const isYou = p.is_you || (youPlayerId && p.id === youPlayerId);

            // Build role tags (compact)
            let roleTag = "";
            if (isYou) {
                roleTag = '<span class="compact-role you-tag">You</span>';
            }

            // Determine which stats to show based on game mode
            let statsHtml = "";
            if (isCardDuel) {
                // Card Duel mode: show HP, Shield, Deck, Hand
                // We need to fetch specific duel stats which might be nested in 'cd' object
                // depending on if 'p' is 'you' or 'opponent'.
                // However, for spectator view or generic list, we might just use 'p' if updated,
                // but 'cd' usually has the authoritative duel stats.
                // Simplified logic: assume 1v1 for now or map 'p.id' to 'cd.you/opponent'.

                let playerData = null;
                if (cd.you && cd.you.player_id === p.id) playerData = cd.you;
                else if (cd.opponent && cd.opponent.player_id === p.id) playerData = cd.opponent;

                // Fallback to 'p' if 'cd' mapping fails (e.g. spectator)
                const hp = playerData?.hp ?? p.hp ?? 0;
                const shield = playerData?.shield ?? 0;
                const deckCount = playerData?.deck_count ?? 0;
                const handCount = playerData?.hand_count ?? (Array.isArray(playerData?.hand) ? playerData.hand.length : 0);

                statsHtml = `
                    <div class="compact-stat-row">
                        <span class="compact-stat hp">❤️ HP: ${hp}</span>
                        <span class="compact-stat shield">🛡️ Shield: ${shield}</span>
                    </div>
                    <div class="compact-stat-row">
                        <span class="compact-stat deck">🃏 Deck: ${deckCount}</span>
                        <span class="compact-stat hand">✋ Hand: ${handCount}</span>
                    </div>
                `;
            } else {
                // Regular board game mode: show HP, Coins, Position
                statsHtml = `
                    <div class="compact-stat-row">
                        <span class="compact-stat hp">❤️ HP: ${p.hp}</span>
                        <span class="compact-stat coins">🪙 Coins: ${p.coins}</span>
                    </div>
                    <div class="compact-stat-row">
                        <span class="compact-stat pos">📍 Pos: ${p.position}</span>
                    </div>
                `;
            }

            return `
                <li class="compact-player-item">
                    <div class="compact-player-header">
                        <span class="compact-player-name">${escapeHtml(p.username)}</span>
                        ${roleTag}
                    </div>
                    <div class="compact-player-stats">
                        ${statsHtml}
                    </div>
                </li>
            `;
        })
        .join("");

    listEl.innerHTML = playersHtml || "<li>No players in this game yet.</li>";
}

// -------------------------------------------------------------------------
// UI: ACTIONS & TURN INFO
// -------------------------------------------------------------------------

/**
 * Updates the dice panel, roll button state, and current turn label.
 */
function updateDiceUI(state) {
    const dicePanel = document.getElementById("dice-panel");
    if (!dicePanel || !state) return;

    const labelEl = document.getElementById("current-turn-label");
    const rollButton = document.getElementById("roll-button");
    const diceDisplay = document.getElementById("dice-display");

    // Handle non-active game states
    if (state.status !== "active") {
        if (labelEl) {
            labelEl.textContent = "Game is not active.";
        }
        if (rollButton) {
            rollButton.disabled = true;
        }
        return;
    }

    const players = Array.isArray(state.players) ? state.players : [];
    const current = players.find(p => p.is_current_turn);
    const youId = state.you_player_id;

    const isYourTurn = current && current.id === youId;

    // Update Turn Label
    if (labelEl) {
        if (current) {
            labelEl.textContent = `Current player: ${current.username}` +
                (isYourTurn ? " (you)" : "");
        } else {
            labelEl.textContent = "Current player: unknown.";
        }
    }

    // Update Roll Button State
    if (rollButton) {
        rollButton.disabled = !isYourTurn || !players.some(p => p.is_alive);
    }

    // Handle Finished Game
    if (state.status === "finished") {
        if (rollButton) rollButton.disabled = true;
        if (labelEl) labelEl.textContent = "Game finished.";
    }

    // Stop polling if finished
    if (state.status === "finished" && window.__gameStateInterval) {
        clearInterval(window.__gameStateInterval);
        window.__gameStateInterval = null;
    }

    // Helper text for dice area
    if (diceDisplay && !diceDisplay.dataset.hasValue) {
        diceDisplay.textContent = isYourTurn
            ? "It is your turn. Roll the dice."
            : "Waiting for the current player to roll.";
    }
}

// -------------------------------------------------------------------------
// API INTERACTIONS
// -------------------------------------------------------------------------

/**
 * Fetches the full game state from the server and updates all UI components.
 * @param {string} gameId - The ID of the current game.
 */
async function fetchGameState(gameId) {
    try {
        const response = await fetch(`/games/${gameId}/state/`, {
            headers: {
                "X-Requested-With": "XMLHttpRequest"
            }
        });
        if (!response.ok) {
            console.error("Failed to fetch game state:", response.status);
            return;
        }

        const data = await response.json();
        updatePlayersUI(data);
        updateDiceUI(data);
        updateBoardUI(data);
    } catch (err) {
        console.error("Error fetching game state:", err);
    }
}

// -------------------------------------------------------------------------
// DICE ROLL ACTION
// -------------------------------------------------------------------------

/**
 * Handles the "Roll Dice" button click.
 * Sends the roll request, updates the UI with the result, and logs the move.
 */
async function handleRollClick(event) {
    event.preventDefault();

    const gameId = window.GAME_ID;
    if (!gameId) return;

    const rollButton = document.getElementById("roll-button");
    const diceDisplay = document.getElementById("dice-display");
    const logEl = document.getElementById("dice-log");

    // Optimistic UI updates
    if (rollButton) {
        rollButton.disabled = true;
    }
    if (diceDisplay) {
        diceDisplay.textContent = "Rolling...";
    }

    try {
        const response = await fetch(`/games/${gameId}/roll/`, {
            method: "POST",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": getCookie("csrftoken") || "",
            },
            body: new FormData(),
        });

        if (!response.ok) {
            let msg = `Error: ${response.status}`;
            try {
                const errData = await response.json();
                if (errData && errData.detail) {
                    msg = errData.detail;
                }
            } catch (_) {
                // ignore
            }

            if (diceDisplay) {
                diceDisplay.textContent = msg;
                diceDisplay.dataset.hasValue = "1";
            }
            // Refresh state to ensure sync
            fetchGameState(gameId);
            return;
        }

        const data = await response.json();

        const result = data.result || data.action || {};
        const dice = result.dice;
        const move = result.move || {};
        const state = data.game_state;

        // Display Roll Result
        if (diceDisplay && typeof dice !== "undefined") {
            diceDisplay.textContent = `You rolled ${dice}.`;
            diceDisplay.dataset.hasValue = "1";
        }

        // Log the move
        if (logEl && move) {
            const from = move.from_position;
            const to = move.to_position;
            const tileType = move.landed_tile_type;
            const tileEffect = move.tile_effect || {};

            let text = `Moved from ${from} to ${to}.`;
            if (tileType) {
                text += ` Landed on ${tileType}.`;
            }
            if (tileEffect.hp_delta) {
                text += ` HP ${tileEffect.hp_delta > 0 ? "+" + tileEffect.hp_delta : tileEffect.hp_delta}.`;
            }
            if (tileEffect.coins_delta) {
                text += ` Coins ${tileEffect.coins_delta > 0 ? "+" + tileEffect.coins_delta : tileEffect.coins_delta}.`;
            }
            if (tileEffect.extra && tileEffect.extra.died) {
                text += " You died.";
            }
            if (tileEffect.extra && tileEffect.extra.opponent_died) {
                text += " Opponent died.";
            }

            const p = document.createElement("p");
            p.textContent = text;
            logEl.prepend(p);
        }

        if (state) {
            updatePlayersUI(state);
            updateDiceUI(state);
            updateBoardUI(state);
        }
    } catch (err) {
        console.error("Error during roll:", err);
        if (diceDisplay) {
            diceDisplay.textContent = "Error while rolling.";
            diceDisplay.dataset.hasValue = "1";
        }
    }
}

// -------------------------------------------------------------------------
// INITIALIZATION
// -------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", function () {
    if (typeof window.GAME_ID === "undefined") {
        console.warn("GAME_ID not defined; cannot start game JS.");
        return;
    }

    // Skip initialization if card_duel.js will handle it
    // (card_duel.js sets this flag)
    if (window.__cardDuelHandlesPolling) {
        console.log("Card duel is handling state polling, skipping game_state.js polling.");
        return;
    }

    // Initial state fetch
    fetchGameState(window.GAME_ID);

    // Poll every 2 seconds to keep everyone in sync
    window.__gameStateInterval = setInterval(function () {
        fetchGameState(window.GAME_ID);
    }, 2000);

    // Wire roll button (if present)
    const rollButton = document.getElementById("roll-button");
    if (rollButton) {
        rollButton.addEventListener("click", handleRollClick);
    }
});

