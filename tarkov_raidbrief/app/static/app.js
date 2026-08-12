/* Small enough to read in one sitting, which is the point: no build step,
   no framework, and it has to keep working on an ARM SBC for years.

   All fetch() URLs are relative so they resolve under the Home Assistant
   Ingress prefix as well as on the direct :8099 port. */

(function () {
  "use strict";

  var STORE_PREFIX = "raidbrief.checked.";
  var LAST_MAP_KEY = "raidbrief.lastMap";
  var STANDING_OPEN_KEY = "raidbrief.standingOpen";

  var select = document.getElementById("map-select");
  var sections = Array.prototype.slice.call(document.querySelectorAll("section.map"));

  /* ---- map switching (all maps are already in the DOM) ---- */

  function show(index) {
    sections.forEach(function (s) {
      s.hidden = String(s.dataset.index) !== String(index);
    });
    var active = sections[index];
    if (active) {
      try { localStorage.setItem(LAST_MAP_KEY, active.dataset.map); } catch (e) { /* private mode */ }
    }
  }

  if (select) {
    select.addEventListener("change", function () { show(select.value); });

    // Come back to the map you were last packing for.
    var last = null;
    try { last = localStorage.getItem(LAST_MAP_KEY); } catch (e) { /* ignore */ }
    if (last) {
      var match = sections.filter(function (s) { return s.dataset.map === last; })[0];
      if (match) { select.value = match.dataset.index; show(match.dataset.index); }
    }
  }

  /* ---- "run next" card jumps to that map ---- */

  var recommend = document.querySelector(".recommend[data-goto]");
  if (recommend && select) {
    recommend.addEventListener("click", function () {
      var wanted = recommend.dataset.goto;
      var target = sections.filter(function (s) {
        var title = s.querySelector(".map-title");
        return title && title.textContent.trim().indexOf(wanted) === 0;
      })[0];
      if (target) {
        select.value = target.dataset.index;
        show(target.dataset.index);
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }

  /* ---- carry-in checkboxes, persisted per map ---- */

  function keyFor(map) { return STORE_PREFIX + map; }

  function loadChecked(map) {
    try {
      return JSON.parse(localStorage.getItem(keyFor(map)) || "[]");
    } catch (e) {
      return [];
    }
  }

  function saveChecked(map, values) {
    try {
      if (values.length) {
        localStorage.setItem(keyFor(map), JSON.stringify(values));
      } else {
        localStorage.removeItem(keyFor(map));
      }
    } catch (e) { /* storage full or blocked; ticking still works for this session */ }
  }

  sections.forEach(function (section) {
    var map = section.dataset.map;
    var boxes = Array.prototype.slice.call(section.querySelectorAll("ul.check input"));
    var checked = loadChecked(map);

    boxes.forEach(function (box) {
      if (checked.indexOf(box.value) !== -1) box.checked = true;
      box.addEventListener("change", function () {
        var current = boxes.filter(function (b) { return b.checked; })
                           .map(function (b) { return b.value; });
        saveChecked(map, current);
      });
    });

    var clear = section.querySelector("[data-clear]");
    if (clear) {
      clear.addEventListener("click", function () {
        boxes.forEach(function (b) { b.checked = false; });
        saveChecked(map, []);
      });
    }
  });

  /* ---- item icons ----
     tarkov.dev has no art for a handful of quest items, and the add-on may be
     running with no route to the internet at all. Either way the row keeps its
     text; only the picture goes, and the empty frame goes with it so the row
     matches the ones that never had an icon. */

  Array.prototype.forEach.call(document.querySelectorAll(".ico img, img.portrait"),
    function (img) {
      img.addEventListener("error", function () {
        var box = img.parentNode;
        img.remove();
        if (box && box.classList.contains("ico")) box.classList.add("empty");
      });
      // A cached failure can beat the listener to the punch.
      if (img.complete && img.naturalWidth === 0) {
        img.dispatchEvent(new Event("error"));
      }
    });

  /* ---- trader standing ----
     Every control here changes which tasks are available, which changes the
     map list, the counts and the recommendation - so the page reloads rather
     than trying to patch a dozen places by hand. */

  var standing = document.getElementById("standing-panel");
  if (standing) {
    try {
      standing.open = localStorage.getItem(STANDING_OPEN_KEY) === "1";
    } catch (e) { /* private mode; it just starts closed */ }

    standing.addEventListener("toggle", function () {
      try {
        localStorage.setItem(STANDING_OPEN_KEY, standing.open ? "1" : "0");
      } catch (e) { /* ignore */ }
    });

    var status = standing.querySelector("[data-standing-status]");

    function saveStanding(body, control) {
      if (control) control.disabled = true;
      if (status) {
        status.className = "standing-note";
        status.textContent = "Saving";
      }

      fetch("api/trader-standing", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body)
      })
        .then(function (r) {
          return r.json().then(function (payload) {
            if (!r.ok) throw new Error(payload.error || "HTTP " + r.status);
            return payload;
          });
        })
        .then(function () {
          // Keep the panel open across the reload: you are usually setting
          // several traders in a row.
          try { localStorage.setItem(STANDING_OPEN_KEY, "1"); } catch (e) { /* ignore */ }
          window.location.reload();
        })
        .catch(function (err) {
          if (control) control.disabled = false;
          if (status) {
            status.className = "standing-note error";
            status.textContent = "Could not save: " + err.message;
          }
        });
    }

    standing.addEventListener("click", function (event) {
      var pip = event.target.closest(".pip");
      if (pip) {
        var levels = {};
        levels[pip.closest(".trader").dataset.trader] = Number(pip.dataset.level);
        saveStanding({ levels: levels }, pip);
        return;
      }
      if (event.target.closest("[data-standing-reset]")) {
        // The button lives inside the <summary>, whose default action is to
        // collapse the panel out from under the click.
        event.preventDefault();
        saveStanding({ reset: true }, event.target);
        return;
      }
      // Writes the levels estimated from completed tasks in as ordinary
      // overrides, which the pips can then correct one by one.
      if (event.target.closest("[data-standing-derive]")) {
        event.preventDefault();
        saveStanding({ apply_derived: true }, event.target);
      }
    });

    standing.addEventListener("change", function (event) {
      var input = event.target.closest("[data-rep]");
      // Blank means "still don't know", which is not the same as zero: the
      // server leaves the reputation gate off until there is a real number.
      if (!input || input.value === "") return;
      var reps = {};
      reps[input.closest(".trader").dataset.trader] = Number(input.value);
      saveStanding({ reputations: reps }, input);
    });
  }

  /* ---- AI, on demand only ----
     Nothing here fires on load. The server never generates while rendering,
     so text appears only because someone pressed a button. */

  function renderParagraphs(container, text) {
    container.textContent = "";
    text.split("\n").forEach(function (para) {
      if (!para.trim()) return;
      var p = document.createElement("p");
      p.textContent = para.trim();      // textContent, so model output can't inject HTML
      container.appendChild(p);
    });
  }

  function askAi(url, button, status, onText) {
    button.disabled = true;
    button.classList.add("loading");
    var original = button.textContent;
    button.textContent = "Thinking";
    if (status) status.textContent = "";

    fetch(url, { method: "POST", headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.json().then(function (body) {
          if (!r.ok) throw new Error(body.error || "HTTP " + r.status);
          return body;
        });
      })
      .then(function (body) {
        onText(body.text);
        button.textContent = "Regenerate";
        if (status) status.textContent = "";
      })
      .catch(function (err) {
        button.textContent = original;
        if (status) status.textContent = err.message;
      })
      .then(function () {
        button.disabled = false;
        button.classList.remove("loading");
      });
  }

  sections.forEach(function (section) {
    var block = section.querySelector("[data-ai-map]");
    if (!block) return;
    var button = block.querySelector(".ai-ask");
    var status = block.querySelector(".ai-status");
    var body = block.querySelector(".ai-body");
    if (!button) return;

    button.addEventListener("click", function () {
      // `force` once text already exists, so "Regenerate" really regenerates
      // instead of handing back the cached copy.
      var force = body.children.length > 0 ? "&force=true" : "";
      askAi("api/ai/map?map=" + encodeURIComponent(block.dataset.aiMap) + force,
            button, status, function (text) { renderParagraphs(body, text); });
    });
  });

  var recBtn = document.querySelector("[data-ai-rec-btn]");
  if (recBtn) {
    recBtn.addEventListener("click", function (event) {
      event.stopPropagation();          // don't also trigger the card's jump-to-map
      var wrap = recBtn.parentNode;
      askAi("api/ai/recommendation", recBtn, null, function (text) {
        var p = document.createElement("p");
        p.className = "ai-body";
        p.textContent = text;
        wrap.replaceChild(p, recBtn);
      });
    });
  }

  /* ---- refresh ---- */

  var refresh = document.getElementById("refresh");
  if (refresh) {
    refresh.addEventListener("click", function () {
      refresh.disabled = true;
      var original = refresh.textContent;
      refresh.textContent = "...";

      fetch("api/refresh", { method: "POST", headers: { "Accept": "application/json" } })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function () { window.location.reload(); })
        .catch(function (err) {
          refresh.disabled = false;
          refresh.textContent = original;
          // The server reports upstream problems as banners; this is for the
          // case where the add-on itself is unreachable.
          alert("Refresh failed: " + err.message);
        });
    });
  }
})();
