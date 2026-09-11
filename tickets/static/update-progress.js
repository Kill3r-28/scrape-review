(function () {
  var buttons = document.querySelectorAll("[data-day-update]");
  if (!buttons.length) return;

  var panel = document.getElementById("update-progress");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "update-progress";
    panel.className = "update-progress";
    panel.hidden = true;
    panel.innerHTML =
      '<div class="update-progress-card">' +
      '<div class="update-progress-head">' +
      "<strong>Updating day</strong>" +
      '<span class="muted small" data-progress-status></span>' +
      "</div>" +
      '<div class="update-progress-bar"><div data-progress-fill></div></div>' +
      '<p class="muted small" data-progress-current></p>' +
      '<ul class="update-progress-log" data-progress-log></ul>' +
      "</div>";
    var main = document.querySelector("main.container");
    if (main) main.insertBefore(panel, main.firstChild);
    else document.body.appendChild(panel);
  }

  var statusEl = panel.querySelector("[data-progress-status]");
  var fillEl = panel.querySelector("[data-progress-fill]");
  var currentEl = panel.querySelector("[data-progress-current]");
  var logEl = panel.querySelector("[data-progress-log]");
  var busy = false;

  function setBusy(on) {
    busy = on;
    buttons.forEach(function (btn) {
      btn.disabled = on;
    });
  }

  function logLine(text, kind) {
    var li = document.createElement("li");
    if (kind) li.className = kind;
    li.textContent = text;
    logEl.appendChild(li);
    logEl.scrollTop = logEl.scrollHeight;
  }

  async function updateDay(dateStr, btn) {
    if (busy) return;
    setBusy(true);
    panel.hidden = false;
    logEl.innerHTML = "";
    fillEl.style.width = "15%";
    statusEl.textContent = dateStr;
    currentEl.textContent = "Scraping " + dateStr + " (smart jump to that day)…";
    if (btn) btn.textContent = "…";

    try {
      var res = await fetch("/admin/update-reports/day", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ date: dateStr, incremental: true }),
      });
      fillEl.style.width = "85%";
      var data = await res.json().catch(function () {
        return { ok: false, error: "Bad response" };
      });
      if (!res.ok || !data.ok) {
        currentEl.textContent = data.error || "Update failed.";
        logLine(dateStr + " — failed: " + (data.error || res.status), "err");
        fillEl.style.width = "100%";
        return;
      }

      if (data.incremental && data.after_creation) {
        logLine("Resumed after " + data.after_creation + " (latest already stored)", "ok");
      } else {
        logLine("Full day scrape for " + dateStr, "ok");
      }
      logLine(
        "Created " +
          (data.created || 0) +
          ", updated " +
          (data.updated || 0) +
          ", skipped " +
          (data.skipped || 0) +
          " (rows " +
          (data.total_rows || 0) +
          ")",
        "ok"
      );
      if (data.criticality_updated) {
        logLine("Criticality set for " + data.criticality_updated + " tickets", "ok");
      }

      fillEl.style.width = "100%";
      statusEl.textContent = "Done";
      currentEl.textContent =
        "Done " +
        dateStr +
        ": +" +
        (data.created || 0) +
        " new. Reloading…";

      var params = new URLSearchParams(window.location.search);
      params.set("start_date", dateStr);
      params.set("end_date", dateStr);
      params.set("cal_year", dateStr.slice(0, 4));
      params.set("cal_month", String(Number(dateStr.slice(5, 7))));
      params.set(
        "msg",
        "Updated " +
          dateStr +
          ": created " +
          (data.created || 0) +
          ", skipped " +
          (data.skipped || 0)
      );
      setTimeout(function () {
        window.location.href = "/?" + params.toString();
      }, 700);
    } catch (err) {
      currentEl.textContent = "Update failed.";
      logLine(String(err), "err");
      fillEl.style.width = "100%";
    } finally {
      setBusy(false);
      if (btn) btn.textContent = "Update";
    }
  }

  buttons.forEach(function (btn) {
    btn.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      var dateStr = btn.getAttribute("data-day-update");
      if (dateStr) updateDay(dateStr, btn);
    });
  });
})();
