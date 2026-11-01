// Browse: the albums as a list or as a grid of covers, remembered for this device. Set on the
// page itself before anything is shown, so a shelf does not jump, and kept when searching while
// typing replaces the page. Without storage or a choice it is the list; without this script
// the switch stays out of sight.
(function () {
  const KEY = "sleeve-shelf-browse-view";
  const root = document.documentElement;
  let view = "list";
  try {
    if (localStorage.getItem(KEY) === "grid") view = "grid";
  } catch (error) {
    // The list, then.
  }
  root.dataset.browseView = view;

  function show() {
    document.querySelectorAll("[data-browse-view-choice]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.browseViewChoice === root.dataset.browseView));
    });
  }

  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-browse-view-choice]");
    if (!button) return;
    root.dataset.browseView = button.dataset.browseViewChoice;
    show();
    try {
      localStorage.setItem(KEY, root.dataset.browseView);
    } catch (error) {
      // For this page only.
    }
  });
  document.addEventListener("DOMContentLoaded", function () {
    show();
    new MutationObserver(show).observe(document.body, { childList: true, subtree: true });
  });
})();
