/**
 * =========================================================================
 * MAIN SITE INTERACTIVITY
 * =========================================================================
 * Core scripts for the main site layout and landing page.
 * - Sticky header shadow effect
 * - User profile dropdown menu
 * - Landing page chest animation cycle
 */

document.addEventListener("DOMContentLoaded", () => {
  // =========================
  // HEADER SHADOW
  // =========================
  const header = document.querySelector(".site-header");
  function updateHeaderShadow() {
    if (!header) return;
    if (window.scrollY > 6) header.classList.add("scrolled");
    else header.classList.remove("scrolled");
  }
  updateHeaderShadow();
  window.addEventListener("scroll", updateHeaderShadow, { passive: true });

  // =========================
  // USER DROPDOWN TOGGLE
  // =========================
  const userTrigger = document.querySelector(".user-menu-trigger");
  const userDropdown = document.querySelector(".user-dropdown");

  if (userTrigger && userDropdown) {
    userTrigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const isActive = userDropdown.classList.contains("active");

      // Close all other dropdowns if any (future proofing)
      document.querySelectorAll(".user-dropdown").forEach(d => d.classList.remove("active"));

      if (!isActive) {
        userDropdown.classList.add("active");
      }
    });

    document.addEventListener("click", (e) => {
      if (!userDropdown.contains(e.target) && !userTrigger.contains(e.target)) {
        userDropdown.classList.remove("active");
      }
    });
  }

  // =========================
  // CHEST ITEM LOOP (Animation)
  // =========================
  const chest = document.getElementById("chest");
  if (!chest) return;

  const chestImg = chest.querySelector(".chest-visual");
  const itemImg = chest.querySelector(".chest-item");

  const closedSrc = chest.dataset.closed;
  const openSrc = chest.dataset.open;

  let items = [];
  try {
    items = JSON.parse(chest.dataset.items || "[]");
  } catch {
    items = [];
  }

  if (!chestImg || !itemImg || !closedSrc || !openSrc || items.length === 0) return;

  // Animation Timings (in milliseconds)
  const CLOSED_TIME = 2000;
  const OPEN_TIME = 5000;

  let idx = 0;

  function setItem(i) {
    itemImg.src = items[i];
  }

  function openChest() {
    chest.classList.add("open");
    chestImg.src = openSrc;
  }

  function closeChest() {
    chest.classList.remove("open");
    chestImg.src = closedSrc;
  }

  // Initial State
  closeChest();
  setItem(idx);

  /**
   * Recursive function to cycle through chest items.
   * Opens chest -> Waits -> Closes chest -> Swaps item -> Repeats.
   */
  function runCycle() {
    setTimeout(() => {
      openChest();

      setTimeout(() => {
        closeChest();
        idx = (idx + 1) % items.length;
        setItem(idx);
        runCycle();
      }, OPEN_TIME);

    }, CLOSED_TIME);
  }

  runCycle();
});
