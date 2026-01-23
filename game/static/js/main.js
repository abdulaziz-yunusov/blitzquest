// static/js/main.js
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
  // CHEST ITEM LOOP (3s + 3s)
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

  // 🔧 VAQTLAR
  const CLOSED_TIME = 2000; // 3 sekund yopiq
  const OPEN_TIME   = 5000; // 3 sekund ochiq

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

  // start holat
  closeChest();
  setItem(idx);

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
