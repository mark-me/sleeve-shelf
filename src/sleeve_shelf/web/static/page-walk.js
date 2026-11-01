// Walking through shelves or albums without aiming for a button: the arrow keys, and a swipe on a
// touch screen. Links marked data-walk="prev" or "next" say where to; a link without an address
// leads nowhere. They are looked up when needed, as searching while typing replaces the page.
(function () {
  const SWIPE = 70; // how far a finger has to go sideways
  const STRAIGHT = 40; // and how far up or down it may wander
  const EDGE = 24; // a swipe from the very edge of the screen is the phone's own gesture
  const NOT_A_SWIPE = ".ss-section-tabs, .ss-tabs, .modal, input, select, textarea, audio, iframe";
  let start = null;

  function walk(direction) {
    const link = document.querySelector('[data-walk="' + direction + '"][href]');
    if (link) window.location.href = link.href;
  }

  document.addEventListener("keydown", function (event) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.target.closest("input, select, textarea, [contenteditable], .modal")) return;
    if (event.key === "ArrowLeft") walk("prev");
    if (event.key === "ArrowRight") walk("next");
  });

  document.addEventListener("touchstart", function (event) {
    const touch = event.touches[0];
    const atEdge = touch.clientX < EDGE || touch.clientX > window.innerWidth - EDGE;
    start = event.touches.length === 1 && !atEdge && !event.target.closest(NOT_A_SWIPE) ? touch : null;
  }, { passive: true });

  document.addEventListener("touchend", function (event) {
    if (!start) return;
    const touch = event.changedTouches[0];
    const sideways = touch.clientX - start.clientX;
    const upDown = Math.abs(touch.clientY - start.clientY);
    start = null;
    if (Math.abs(sideways) >= SWIPE && upDown <= STRAIGHT) walk(sideways > 0 ? "prev" : "next");
  }, { passive: true });
})();
