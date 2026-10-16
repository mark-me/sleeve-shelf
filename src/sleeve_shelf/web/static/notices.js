// A notice such as "Saved." or an error comes with the address after a change. It is shown
// once: the address loses it at once, so reloading the page, going back to it, or opening it
// later does not show it again.
(function () {
  const NOTICES = ["saved", "moved", "added", "dismissed", "error", "placed", "picture_error", "swapped", "message", "password", "password_error"];
  const url = new URL(window.location.href);
  let changed = false;
  for (const name of NOTICES) {
    if (url.searchParams.has(name)) {
      url.searchParams.delete(name);
      changed = true;
    }
  }
  if (changed) history.replaceState(history.state, "", url.pathname + url.search + url.hash);
})();
