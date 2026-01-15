// ----------------- Helpers -----------------

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

// ----------------- UI: Board rendering -----------------

function updateBoardUI(state) {
    if (!state) return;

    const container = document.getElementById("board-tiles");
    if (!container) return;

    const tiles = Array.isArray(state.tiles) ? state.tiles : [];
    const players = Array.isArray(state.players) ? state.players : [];

    // Map players by position
    const playersByPos = {};
    for (const p of players) {
        const pos = p.position || 0;
        if (!playersByPos[pos]) {
            playersByPos[pos] = [];
        }
        playersByPos[pos].push(p);
    }

    const tilesHtml = tiles
        .map((tile) => {
            const tPlayers = playersByPos[tile.position] || [];

            const hasCurrent = tPlayers.some(p => p.is_current_turn);

            // Fallback label
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

// ----------------- UI: players panel -----------------

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

    const playersHtml = players
        .map((p) => {
            const isHost = (hostUserId !== null && p.user_id === hostUserId);
            const isFirstTurnOrder = p.turn_order === 0;

            let rolesHtml = "";
            if (isHost) {
                rolesHtml += '<span class="player-role">Host</span>';
            }
            if (isFirstTurnOrder) {
                rolesHtml += '<span class="player-role player-role-turn">Turn order #1</span>';
            }
            if (p.is_current_turn) {
                rolesHtml += '<span class="player-role player-role-turn">Current turn</span>';
            }
            if (p.is_you) {
                rolesHtml += '<span class="player-role player-role-you">You</span>';
            }

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
                        <span class="player-stat">
                            HP: <strong>${p.hp}</strong>
                        </span>
                        <span class="player-stat">
                            Coins: <strong>${p.coins}</strong>
                        </span>
                        <span class="player-stat">
                            Pos: <strong>${p.position}</strong>
                        </span>
                        <span class="player-stat">
                            ${statusBadge}
                        </span>
                    </div>
                </li>
            `;
        })
        .join("");

    listEl.innerHTML = playersHtml || "<li>No players in this game yet.</li>";
}

// ----------------- UI: dice / turn panel -----------------

function updateDiceUI(state) {
    const dicePanel = document.getElementById("dice-panel");
    if (!dicePanel || !state) return;

    const labelEl = document.getElementById("current-turn-label");
    const rollButton = document.getElementById("roll-button");
    const diceDisplay = document.getElementById("dice-display");

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

    if (labelEl) {
        if (current) {
            labelEl.textContent = `Current player: ${current.username}` +
                (isYourTurn ? " (you)" : "");
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

    if (state.status === "finished" && window.__gameStateInterval) {
        clearInterval(window.__gameStateInterval);
        window.__gameStateInterval = null;
    }

    if (diceDisplay && !diceDisplay.dataset.hasValue) {
        diceDisplay.textContent = isYourTurn
            ? "It is your turn. Roll the dice."
            : "Waiting for the current player to roll.";
    }
}

// ----------------- Fetch game state -----------------

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

// ----------------- Roll dice action -----------------

async function handleRollClick(event) {
    event.preventDefault();

    const gameId = window.GAME_ID;
    if (!gameId) return;

    const rollButton = document.getElementById("roll-button");
    const diceDisplay = document.getElementById("dice-display");
    const logEl = document.getElementById("dice-log");

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
            // Refresh state anyway
            fetchGameState(gameId);
            return;
        }

        const data = await response.json();

        const result = data.result || data.action || {};
        const dice = result.dice;
        const move = result.move || {};
        const state = data.game_state;

        if (diceDisplay && typeof dice !== "undefined") {
            diceDisplay.textContent = `You rolled ${dice}.`;
            diceDisplay.dataset.hasValue = "1";
        }

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

// ----------------- Init -----------------

document.addEventListener("DOMContentLoaded", function () {
    if (typeof window.GAME_ID === "undefined") {
        console.warn("GAME_ID not defined; cannot start game JS.");
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
