// Countdown to the next game night, and confirm prompts for destructive
// forms. External file (not inline) so the CSP can forbid inline script.
(function () {
  var el = document.getElementById("countdown");
  if (el) {
    var target = new Date(el.dataset.target).getTime();
    var tick = function () {
      var ms = target - Date.now();
      if (ms <= 0) { el.textContent = "It's game night! 🎉"; return; }
      var s = Math.floor(ms / 1000);
      var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600),
          m = Math.floor(s % 3600 / 60), sec = s % 60;
      el.innerHTML = [[d, "days"], [h, "hours"], [m, "min"], [sec, "sec"]].map(function (p) {
        return '<span class="unit"><b>' + p[0] + "</b>" + p[1] + "</span>";
      }).join("");
      setTimeout(tick, 1000);
    };
    tick();
  }
  document.addEventListener("submit", function (e) {
    var msg = e.target.dataset && e.target.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  });
  // Tap-to-show for the affiliation tooltips on touch screens.
  document.querySelectorAll(".chip").forEach(function (c) {
    c.addEventListener("click", function () { c.classList.toggle("open"); });
  });
})();
