// Small, vanilla, no framework (SPEC 13.1). Everything important is server-rendered;
// this only handles the things a static page genuinely can't do.

(function () {
  "use strict";

  // -- theme, remembered per browser ------------------------------------
  var root = document.documentElement;
  try {
    var saved = localStorage.getItem("trail-theme");
    if (saved) root.setAttribute("data-theme", saved);
  } catch (e) { /* private windows throw; the OS preference still applies */ }

  var toggle = document.querySelector("[data-theme-toggle]");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var dark = root.getAttribute("data-theme") === "dark" ||
        (!root.hasAttribute("data-theme") &&
          window.matchMedia("(prefers-color-scheme: dark)").matches);
      var next = dark ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("trail-theme", next); } catch (e) {}
    });
  }

  // -- "new runs synced" banner -----------------------------------------
  var poll = document.querySelector("[data-stamp-url]");
  if (poll) {
    var known = parseFloat(poll.getAttribute("data-stamp") || "0");
    setInterval(function () {
      fetch(poll.getAttribute("data-stamp-url"))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.stamp && data.stamp > known) {
            var banner = document.querySelector("[data-refresh-banner]");
            if (banner) banner.hidden = false;
          }
        })
        .catch(function () { /* the server going away is not worth shouting about */ });
    }, 5000);
  }

  // -- queue an analysis and watch it -----------------------------------
  function watchJob(id, button, logEl) {
    var timer = setInterval(function () {
      fetch("/api/jobs/" + id)
        .then(function (r) { return r.json(); })
        .then(function (job) {
          if (logEl) {
            logEl.textContent = (job.progress ? job.progress + "  " : "") +
              (job.detail.length ? job.detail[job.detail.length - 1] : "working…");
          }
          if (job.status === "done") {
            clearInterval(timer);
            window.location.reload();
          } else if (job.status === "failed") {
            clearInterval(timer);
            button.disabled = false;
            button.textContent = "Explain this step";
            if (logEl) logEl.textContent = job.message || "That didn't work.";
          }
        })
        .catch(function () {
          clearInterval(timer);
          button.disabled = false;
          if (logEl) logEl.textContent = "Lost contact with the viewer.";
        });
    }, 1500);
  }

  document.querySelectorAll("[data-analyze]").forEach(function (button) {
    button.addEventListener("click", function () {
      var project = button.getAttribute("data-project");
      var step = button.getAttribute("data-analyze");
      var body = step === "all" ? { all_pending: true } : { steps: [step] };
      var count = parseInt(button.getAttribute("data-count") || "1", 10);
      if (count > 3 && !window.confirm("Explain " + count + " checkpoints? Each one calls Claude.")) {
        return;
      }
      var logEl = button.parentNode.querySelector("[data-job-log]");
      button.disabled = true;
      button.textContent = "Asking Claude…";
      fetch("/api/p/" + encodeURIComponent(project) + "/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.error) {
            button.disabled = false;
            button.textContent = "Explain this step";
            if (logEl) logEl.textContent = data.error;
            return;
          }
          watchJob(data.job.id, button, logEl);
        })
        .catch(function () {
          button.disabled = false;
          if (logEl) logEl.textContent = "Couldn't reach the viewer.";
        });
    });
  });

  // -- pick two versions to compare -------------------------------------
  document.querySelectorAll("[data-version]").forEach(function (knot) {
    knot.addEventListener("click", function () {
      var n = knot.getAttribute("data-version");
      var url = new URL(window.location.href);
      var a = url.searchParams.get("a");
      var b = url.searchParams.get("b");
      // Clicking always sets B and slides the old B into A, so two clicks pick a range.
      if (a === n || b === n) return;
      url.searchParams.set("a", b || a || n);
      url.searchParams.set("b", n);
      window.location.href = url.toString();
    });
  });

  // -- cell actions ------------------------------------------------------
  document.querySelectorAll("[data-cell-action]").forEach(function (button) {
    button.addEventListener("click", function () {
      var action = button.getAttribute("data-cell-action");
      var project = button.getAttribute("data-project");
      var identity = button.getAttribute("data-identity");
      var body = { action: action };
      if (action === "rename") {
        var name = window.prompt("What should this cell be called?",
          button.getAttribute("data-name") || "");
        if (!name) return;
        body.name = name;
      }
      fetch("/api/p/" + encodeURIComponent(project) + "/cells/" + identity, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).then(function () { window.location.reload(); });
    });
  });

  // -- side-by-side / one-column diff ------------------------------------
  document.querySelectorAll("[data-diff-view]").forEach(function (button) {
    button.addEventListener("click", function () {
      var wanted = button.getAttribute("data-diff-view");
      document.querySelectorAll("[data-diff-view]").forEach(function (other) {
        other.setAttribute("aria-pressed", String(other === button));
      });
      document.querySelectorAll("[data-diff-pane]").forEach(function (pane) {
        pane.hidden = pane.getAttribute("data-diff-pane") !== wanted;
      });
      try { localStorage.setItem("trail-diff-view", wanted); } catch (e) {}
    });
  });
  try {
    var savedView = localStorage.getItem("trail-diff-view");
    if (savedView) {
      var target = document.querySelector('[data-diff-view="' + savedView + '"]');
      if (target) target.click();
    }
  } catch (e) {}

  // -- story mode keyboard ----------------------------------------------
  var chapters = Array.prototype.slice.call(document.querySelectorAll(".chapter"));
  if (chapters.length) {
    var at = 0;
    function go(delta) {
      at = Math.max(0, Math.min(chapters.length - 1, at + delta));
      chapters[at].scrollIntoView({ behavior: "smooth", block: "start" });
      var links = document.querySelectorAll(".rail a");
      links.forEach(function (a, i) { a.classList.toggle("is-current", i === at); });
    }
    document.addEventListener("keydown", function (event) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      var tag = (event.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      if (event.key === "j" || event.key === "ArrowDown") { go(1); event.preventDefault(); }
      else if (event.key === "k" || event.key === "ArrowUp") { go(-1); event.preventDefault(); }
      else if (event.key === "e") {
        var open = chapters[at].querySelector("details");
        if (open) open.open = !open.open;
      }
    });

    if ("IntersectionObserver" in window) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var index = chapters.indexOf(entry.target);
          if (index >= 0) {
            at = index;
            document.querySelectorAll(".rail a").forEach(function (a, i) {
              a.classList.toggle("is-current", i === index);
            });
          }
        });
      }, { rootMargin: "-20% 0px -70% 0px" });
      chapters.forEach(function (c) { observer.observe(c); });
    }
  }
})();
