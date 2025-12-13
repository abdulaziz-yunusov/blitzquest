function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function updateLobbyPlayers(state) {
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

async function fetchLobbyState(gameId) {
    try {
        const resp = await fetch(`/games/${gameId}/state/`, {
            headers: { "X-Requested-With": "XMLHttpRequest" }
        });
        if (!resp.ok) return;
        const data = await resp.json();

        // only care while waiting / active
        if (data.status === "waiting" || data.status === "active") {
            updateLobbyPlayers(data);
        }
    } catch (e) {
        console.error("Lobby state error:", e);
    }
}

document.addEventListener("DOMContentLoaded", function () {
    if (typeof window.GAME_ID === "undefined") return;

    fetchLobbyState(window.GAME_ID);
    window.__lobbyInterval = setInterval(function () {
        fetchLobbyState(window.GAME_ID);
    }, 2000);
});
