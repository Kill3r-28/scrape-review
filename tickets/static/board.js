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

  function boardStatusFilter() {
    return (
      document.querySelector("[data-board-stats]")?.dataset.statusFilter || "open"
    );
  }

  function markRowResolved(row, prevStatus, reportDate, { delayVanish = 3000 } = {}) {
    if (!row || row.dataset.status === "resolved") return false;

    const fromStatus = prevStatus || row.dataset.status || "open";
    row.dataset.status = "resolved";
    row.classList.add("row-resolved-pending");

    const badge = row.querySelector("[data-status-badge]");
    if (badge) {
      badge.className = "badge status-resolved";
      badge.textContent = "resolved";
    }

    const btn = row.querySelector("button.btn-resolve");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Resolved";
      btn.classList.add("is-resolved");
    }

    row.querySelectorAll("[data-not-mine], form:not(.js-quick-resolve)").forEach((el) => {
      el.remove();
    });

    if (fromStatus === "open") bumpCount("open", -1);
    else if (fromStatus === "in_progress") bumpCount("in_progress", -1);
    bumpCount("resolved", 1);
    updateCalendarDay(reportDate || row.dataset.reportDate || "", fromStatus);

    const filter = boardStatusFilter();
    if (filter === "open" || filter === "in_progress") {
      setTimeout(() => removeRowSmooth(row), delayVanish);
    }
    return true;
  }

  function applyRemoteStatus(payload) {
    if (!payload || payload.status !== "resolved") return;
    const ids = Array.isArray(payload.ticket_ids) && payload.ticket_ids.length
      ? payload.ticket_ids
      : payload.ticket_id
        ? [payload.ticket_id]
        : [];
    ids.forEach((id) => {
      const row = document.querySelector(`[data-ticket-row][data-ticket-id="${id}"]`);
      if (!row) return;
      markRowResolved(row, payload.prev_status || row.dataset.status, payload.report_date, {
        delayVanish: 800,
      });
    });
  }

  async function syncBoardFromServer() {
    if (!onBoard) return;
    const rows = [...document.querySelectorAll("[data-ticket-row]")];
    if (!rows.length) return;
    const ids = rows.map((row) => row.dataset.ticketId).filter(Boolean);
    try {
      const res = await fetch("/api/tickets/statuses?ids=" + encodeURIComponent(ids.join(",")), {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => ({ ok: false }));
      if (!res.ok || !data.ok || !Array.isArray(data.tickets)) return;
      data.tickets.forEach((ticket) => {
        if (ticket.status !== "resolved") return;
        const row = document.querySelector(
          `[data-ticket-row][data-ticket-id="${ticket.id}"]`
        );
        if (!row || row.dataset.status === "resolved") return;
        markRowResolved(row, row.dataset.status, ticket.report_date || "", {
          delayVanish: 400,
        });
      });
    } catch (_err) {
      /* ignore transient sync errors */
    }
  }

  const onBoard = Boolean(document.querySelector("[data-board-stats]"));
  if (onBoard && window.TicketSync) {
    window.TicketSync.subscribe(applyRemoteStatus);
  }
  if (onBoard) {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") syncBoardFromServer();
    });
    window.addEventListener("focus", syncBoardFromServer);
    // Catch resolves that happened while this tab was open but sync messaging failed.
    setInterval(syncBoardFromServer, 5000);
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

        markRowResolved(row, prevStatus, data.report_date || row.dataset.reportDate || "");
        if (window.TicketSync) {
          window.TicketSync.publish({
            type: "status",
            ticket_id: data.ticket_id || Number(row.dataset.ticketId),
            ticket_ids: [data.ticket_id || Number(row.dataset.ticketId)],
            status: "resolved",
            prev_status: prevStatus,
            report_date: data.report_date || row.dataset.reportDate || "",
          });
        }
      } catch (_err) {
        btn.disabled = false;
        btn.textContent = "Resolve";
      }
    });
  });

  // Detail page: save resolution via fetch and notify the board tab.
  const detailForm = document.querySelector("form.form-grid[action*='/update']");
  if (detailForm && !onBoard) {
    detailForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const btn = detailForm.querySelector('button[type="submit"]');
      const statusSelect = detailForm.querySelector('select[name="status"]');
      const prevStatus =
        document.querySelector(".detail-head .badge[class*='status-']")?.textContent
          ?.trim()
          .replace(/\s+/g, "_") || "open";
      if (btn) {
        btn.disabled = true;
        btn.dataset.originalText = btn.textContent;
        btn.textContent = "Saving…";
      }
      try {
        const res = await fetch(detailForm.action, {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
          body: new FormData(detailForm),
        });
        const data = await res.json().catch(() => ({ ok: false }));
        if (!res.ok || !data.ok) {
          if (btn) {
            btn.disabled = false;
            btn.textContent = btn.dataset.originalText || "Save";
          }
          detailForm.submit();
          return;
        }

        if (data.status === "resolved" && window.TicketSync) {
          window.TicketSync.publish({
            type: "status",
            ticket_id: data.ticket_id,
            ticket_ids: data.ticket_ids || [data.ticket_id],
            status: "resolved",
            prev_status: data.prev_status || prevStatus,
            report_date: data.report_date || "",
          });
        }

        if (data.redirect) {
          window.location.href = data.redirect;
          return;
        }

        // Stay on detail in this tab; refresh so badges/notes match server.
        window.location.reload();
      } catch (_err) {
        if (btn) {
          btn.disabled = false;
          btn.textContent = btn.dataset.originalText || "Save";
        }
        detailForm.submit();
      }
    });
  }
})();
