(function () {
  const modal = document.getElementById("not-mine-modal");
  if (!modal) return;

  const form = modal.querySelector("form");
  const reason = modal.querySelector('textarea[name="reason"]');
  const title = modal.querySelector("[data-modal-title]");

  function openModal(action, ticketLabel) {
    form.action = action;
    reason.value = "";
    if (title) title.textContent = ticketLabel || "Why isn't this ticket yours?";
    modal.hidden = false;
    document.body.classList.add("modal-open");
    reason.focus();
  }

  function closeModal() {
    modal.hidden = true;
    document.body.classList.remove("modal-open");
  }

  document.querySelectorAll("[data-not-mine]").forEach((btn) => {
    btn.addEventListener("click", () => {
      openModal(btn.dataset.notMineAction, btn.dataset.notMineLabel || "");
    });
  });

  modal.querySelectorAll("[data-modal-close]").forEach((el) => {
    el.addEventListener("click", closeModal);
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeModal();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) closeModal();
  });
})();
