document.addEventListener("DOMContentLoaded", () => {
  // =========================
  // HEADER SHADOW
  // =========================
  const header = document.querySelector(".site-header");
  function updateHeaderShadow() {
    if (!header) return;
    window.scrollY > 6
      ? header.classList.add("scrolled")
      : header.classList.remove("scrolled");
  }
  updateHeaderShadow();
  window.addEventListener("scroll", updateHeaderShadow, { passive: true });

  // =========================
  // CHEST AUTO LOOP
  // =========================
  const chest = document.getElementById("chest");
  if (!chest) return;

  const chestImg = chest.querySelector(".chest-visual");
  const closedSrc = chest.dataset.closed;
  const openSrc = chest.dataset.open;

  let userOpened = false; // agar user bosib ochsa loop to‘xtaydi
  let loopTimer = null;

  function openChest() {
    if (userOpened) return;
    chest.classList.add("open");
    if (openSrc) chestImg.src = openSrc;
  }

  function closeChest() {
    if (userOpened) return;
    chest.classList.remove("open");
    if (closedSrc) chestImg.src = closedSrc;
  }

  function startChestLoop() {
    // 1s yopiq → ochiladi
    setTimeout(() => {
      openChest();

      // 3s ochiq turadi
      setTimeout(() => {
        closeChest();
      }, 3000);

    }, 1000);
  }

  // 🔁 Loop every 4s
  startChestLoop();
  loopTimer = setInterval(startChestLoop, 4000);

  // =========================
  // USER CLICK → STOP LOOP
  // =========================
  chest.addEventListener("click", () => {
    userOpened = true;
    clearInterval(loopTimer);
    openChest();
  });
});
