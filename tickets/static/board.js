(function () {
  const modal = document.getElementById("not-mine-modal");
  if (modal) {
    const form = modal.querySelector("form");
    const reason = modal.querySelector('textarea[name="reason"]');
    const title = modal.querySelector("[data-modal-title]");
    const returnInput = modal.querySelector("[data-return-to-input]");

    function openModal(action, ticketLabel, returnTo) {
      form.action = action;
      reason.value = "";
      if (returnInput) returnInput.value = returnTo || "";
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
        openModal(
          btn.dataset.notMineAction,
          btn.dataset.notMineLabel || "",
          btn.dataset.returnTo || ""
        );
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
  }

  function bumpCount(key, delta) {
    const el = document.querySelector(`[data-count="${key}"]`);
    if (!el) return;
    const next = Math.max(0, (parseInt(el.textContent, 10) || 0) + delta);
    el.textContent = String(next);
  }

  function updateCalendarDay(reportDate, prevStatus) {
    if (!reportDate) return;
    const cell = document.querySelector(`[data-cal-date="${reportDate}"]`);
    if (!cell) return;

    const openEl = cell.querySelector(".open-count");
    const doneEl = cell.querySelector(".done-count");
    if (openEl && (prevStatus === "open" || prevStatus === "in_progress")) {
      const match = openEl.textContent.match(/(\d+)/);
      if (match) {
        const n = Math.max(0, parseInt(match[1], 10) - 1);
        openEl.textContent = `Open ${n}`;
      }
    }
    if (doneEl) {
      const match = doneEl.textContent.match(/(\d+)/);
      if (match) {
        doneEl.textContent = `Done ${parseInt(match[1], 10) + 1}`;
      }
    }
  }

  function removeRowSmooth(row) {
    if (row.dataset.leaving === "1") return;
    row.dataset.leaving = "1";
    // Force reflow so the leave transition always runs on <td>s.
    void row.offsetHeight;
    row.classList.add("row-leaving");
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      row.remove();
      const tbody = document.querySelector("table tbody");
      if (tbody && !tbody.querySelector("[data-ticket-row]")) {
        const wrap = document.querySelector(".table-wrap");
        if (wrap) {
          wrap.outerHTML =
            '<div class="empty"><h2>No tickets match</h2><p class="muted">Try clearing the date range or other filters.</p></div>';
        }
      }
    };
    const firstCell = row.querySelector("td");
    if (firstCell) {
      firstCell.addEventListener("transitionend", finish, { once: true });
    }
    setTimeout(finish, 500);
  }

  document.querySelectorAll("form.js-quick-resolve").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const btn = form.querySelector("button.btn-resolve");
      const row = form.closest("[data-ticket-row]");
      if (!btn || !row || btn.disabled) return;

      const prevStatus = row.dataset.status || "open";
      btn.disabled = true;
      btn.textContent = "…";

      try {
        const res = await fetch(form.action, {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await res.json().catch(() => ({ ok: false }));
        if (!res.ok || !data.ok) {
          btn.disabled = false;
          btn.textContent = "Resolve";
          return;
        }

        btn.textContent = "Resolved";
        btn.classList.add("is-resolved");
        row.classList.add("row-resolved-pending");

        const badge = row.querySelector("[data-status-badge]");
        if (badge) {
          badge.className = "badge status-resolved";
          badge.textContent = "resolved";
        }
        row.dataset.status = "resolved";

        if (prevStatus === "open") bumpCount("open", -1);
        else if (prevStatus === "in_progress") bumpCount("in_progress", -1);
        bumpCount("resolved", 1);
        updateCalendarDay(data.report_date || row.dataset.reportDate || "", prevStatus);

        const filter =
          document.querySelector("[data-board-stats]")?.dataset.statusFilter ||
          "open";
        const shouldVanish = filter === "open" || filter === "in_progress";

        row.querySelectorAll("[data-not-mine], form:not(.js-quick-resolve)").forEach((el) => {
          el.remove();
        });

        if (shouldVanish) {
          setTimeout(() => removeRowSmooth(row), 3000);
        }
      } catch (_err) {
        btn.disabled = false;
        btn.textContent = "Resolve";
      }
    });
  });
})();
