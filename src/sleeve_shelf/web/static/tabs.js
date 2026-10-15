// Rows that scroll sideways on a narrow screen — the tabs of a section, the letters of the
// artist list: the current one is brought into view, and an edge fades where more is out
// of sight.
(function () {
  document.querySelectorAll(".ss-section-tabs, .ss-letters").forEach(function (bar) {
    const active = bar.querySelector("a.active");
    if (active) bar.scrollLeft = active.offsetLeft - bar.offsetLeft - (bar.clientWidth - active.offsetWidth) / 2;

    function edges() {
      const more = bar.scrollWidth - bar.clientWidth;
      bar.classList.toggle("ss-more-before", bar.scrollLeft > 2);
      bar.classList.toggle("ss-more-after", bar.scrollLeft < more - 2);
    }
    edges();
    bar.addEventListener("scroll", edges, { passive: true });
    window.addEventListener("resize", edges);
  });
})();
