// Edit mode for view chrome.
//
// Click the "edit" toggle in the topnav → body.editing turns on; every
// span.ed becomes contenteditable, with a dashed outline. On blur, the new
// text POSTs to /view-text/<key>, which writes an IS-binding under
// `name = view:<key>` in abra. Toggle off to return to normal view.
//
// abra is the store — no localStorage, no per-device stand-in.
(function () {
  "use strict";

  function base() {
    // Detect mount prefix from this script's own src.
    var s = document.currentScript || document.querySelector('script[src$="/edit.js"]');
    if (!s) return "";
    var src = s.getAttribute("src") || "";
    return src.replace(/\/edit\.js.*$/, "");
  }
  var BASE = base();

  function attach(el) {
    if (el.dataset._editWired) return;
    el.dataset._editWired = "1";
    el.addEventListener("blur", function () {
      var key = el.dataset.k;
      if (!key) return;
      var value = (el.innerText || "").trim();
      var body = new URLSearchParams();
      body.set("value", value);
      fetch(BASE + "/view-text/" + encodeURIComponent(key), {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      }).then(function (resp) {
        return resp.text();
      }).then(function (rendered) {
        // The server returns the resolved text (override-or-default).
        el.innerText = rendered;
      }).catch(function () {
        // Network failure — leave as-typed; user can refresh.
      });
    });
    // Don't navigate the link when the user is editing it.
    if (el.closest("a")) {
      el.addEventListener("click", function (e) {
        if (document.body.classList.contains("editing")) e.preventDefault();
      });
    }
  }

  function refresh() {
    var editing = document.body.classList.contains("editing");
    document.querySelectorAll(".ed").forEach(function (el) {
      attach(el);
      el.setAttribute("contenteditable", editing ? "plaintext-only" : "false");
      el.spellcheck = editing;
    });
    if (sortable) sortable.option("disabled", !editing);
  }

  document.addEventListener("DOMContentLoaded", refresh);

  // Observe class changes on body so toggling "editing" updates contenteditable.
  new MutationObserver(refresh).observe(document.body, {
    attributes: true, attributeFilter: ["class"],
  });

  // ESC exits edit mode. Lets the user bail out without hunting the toggle.
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.body.classList.contains("editing")) {
      document.body.classList.remove("editing");
      if (document.activeElement && document.activeElement.blur) {
        document.activeElement.blur();
      }
    }
  });

  // Pen toggle (.item-edit-toggle) flips body.editing. Event-delegated so
  // pens added later (via htmx swap) work without rewiring. stopPropagation
  // so clicking a pen inside a <summary> doesn't also toggle the <details>.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".item-edit-toggle");
    if (!btn) return;
    e.stopPropagation();
    document.body.classList.toggle("editing");
  });

  // ── Drag-to-reorder the bindings list ────────────────────────────────────
  // Lives in edit.js (not in any one template) so it works wherever a
  // #binding-list <ul.binding-list> is rendered — /bindings/ and the
  // embed inside /cat/<code>/. Sortable.js must be loaded by the page.
  // Persists the order as 'long' scores in user_signal; the server
  // re-renders sorted by those scores on next list-render.
  var sortable = null;
  function initBindingSort() {
    var list = document.querySelector("#binding-list ul.binding-list");
    if (!list || typeof Sortable === "undefined") return;
    if (sortable) { try { sortable.destroy(); } catch (_) {} sortable = null; }
    sortable = new Sortable(list, {
      disabled: !document.body.classList.contains("editing"),
      animation: 150,
      ghostClass: "drag-ghost",
      handle: ".drag-handle",
      onEnd: function () {
        var names = Array.from(list.querySelectorAll("li .name-text"))
                         .map(function (s) { return s.textContent; });
        fetch(BASE + "/signals/reorder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ names: names })
        });
      }
    });
  }
  document.addEventListener("DOMContentLoaded", initBindingSort);
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    if (evt.detail && evt.detail.target && evt.detail.target.id === "binding-list") {
      initBindingSort();
    }
  });

  // ── Persisted UI toggles ─────────────────────────────────────────────
  // Any element with `data-ui-pref="ui.<key>"` becomes a persisted body-
  // class toggle. The server already applied the initial body class on
  // page render from the persisted value; click flips it and POSTs the
  // new state back to abra. The same view-text endpoint accepts both
  // editable labels (free text) and ui.* (boolean as "1" / "").
  window.UI_PREFS = {
    "ui.show-codes":    "show-codes",
    "ui.hide-col.rel":  "hide-rel",
    "ui.hide-col.qual": "hide-qual",
    "ui.hide-col.tgt":  "hide-tgt",
    "ui.hide-col.date": "hide-date",
    "ui.hide-col.from": "hide-from",
  };
  document.querySelectorAll("[data-ui-pref]").forEach(function (el) {
    var key = el.dataset.uiPref;
    var cls = window.UI_PREFS[key];
    if (!cls) return;
    el.addEventListener("click", function () {
      var on = !document.body.classList.contains(cls);
      document.body.classList.toggle(cls, on);
      el.classList.toggle("hidden", on);  // for column toggles' strike-through
      var body = new URLSearchParams();
      body.set("value", on ? "1" : "");
      fetch(BASE + "/view-text/" + encodeURIComponent(key), {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      });
    });
  });
})();
