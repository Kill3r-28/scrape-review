(function () {
  var form = document.getElementById("admin-update-form");
  var btn = document.getElementById("admin-update-btn");
  if (!form || !btn) return;

  var panel = document.getElementById("update-progress");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "update-progress";
    panel.className = "update-progress";
    panel.hidden = true;
    panel.innerHTML =
      '<div class="update-progress-card">' +
      '<div class="update-progress-head">' +
      "<strong>Updating reports</strong>" +
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

  function setProgress(done, total) {
    var pct = total ? Math.round((done / total) * 100) : 0;
    fillEl.style.width = pct + "%";
    statusEl.textContent = done + " / " + total + " days (" + pct + "%)";
  }

  function logLine(text, kind) {
    var li = document.createElement("li");
    if (kind) li.className = kind;
    li.textContent = text;
    logEl.appendChild(li);
    logEl.scrollTop = logEl.scrollHeight;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    runUpdate();
  });

  async function runUpdate() {
    var yearInput = form.querySelector('input[name="year"]');
    var monthInput = form.querySelector('input[name="month"]');
    var year = yearInput ? yearInput.value : "";
    var month = monthInput ? monthInput.value : "";

    btn.disabled = true;
    btn.textContent = "Updating…";
    panel.hidden = false;
    logEl.innerHTML = "";
    setProgress(0, 0);
    currentEl.textContent = "Planning days to fetch…";

    try {
      var planRes = await fetch(
        "/admin/update-reports/plan?year=" +
          encodeURIComponent(year) +
          "&month=" +
          encodeURIComponent(month),
        { credentials: "same-origin" }
      );
      var plan = await planRes.json();
      if (!plan.ok) {
        currentEl.textContent = plan.error || "Could not start update.";
        logLine(plan.error || "Plan failed", "err");
        return;
      }

      var dates = plan.dates || [];
      var total = dates.length;
      var created = 0;
      var skipped = 0;
      setProgress(0, total);
      currentEl.textContent =
        "Fetching " + plan.start + " → " + plan.end + " (" + total + " days)";

      for (var i = 0; i < dates.length; i++) {
        var day = dates[i];
        currentEl.textContent = "Fetching " + day + "…";
        setProgress(i, total);
        var dayRes = await fetch("/admin/update-reports/day", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ date: day }),
        });
        var dayJson = await dayRes.json().catch(function () {
          return { ok: false, error: "Bad response" };
        });
        if (!dayJson.ok) {
          logLine(day + " — failed: " + (dayJson.error || dayRes.status), "err");
        } else {
          created += dayJson.created || 0;
          skipped += dayJson.skipped || 0;
          logLine(
            day +
              " — created " +
              (dayJson.created || 0) +
              ", skipped " +
              (dayJson.skipped || 0) +
              " (rows " +
              (dayJson.total_rows || 0) +
              ")",
            "ok"
          );
        }
        setProgress(i + 1, total);
      }

      currentEl.textContent = "Assigning criticality…";
      var finRes = await fetch("/admin/update-reports/finalize", {
        method: "POST",
        credentials: "same-origin",
      });
      var fin = await finRes.json().catch(function () {
        return { ok: false };
      });
      if (fin.ok) {
        logLine(
          "Criticality updated for " + (fin.criticality_updated || 0) + " tickets",
          "ok"
        );
      } else {
        logLine("Criticality step failed: " + (fin.error || finRes.status), "err");
      }

      currentEl.textContent =
        "Done. Created " + created + ", skipped " + skipped + ". Reloading…";
      setProgress(total, total);
      var reload =
        "/?cal_year=" +
        encodeURIComponent(plan.year) +
        "&cal_month=" +
        encodeURIComponent(plan.month) +
        "&msg=" +
        encodeURIComponent(
          "Updated " +
            plan.start +
            " → " +
            plan.end +
            ": created " +
            created +
            ", skipped " +
            skipped
        );
      setTimeout(function () {
        window.location.href = reload;
      }, 900);
    } catch (err) {
      currentEl.textContent = "Update failed.";
      logLine(String(err), "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "Update";
    }
  }
})();
