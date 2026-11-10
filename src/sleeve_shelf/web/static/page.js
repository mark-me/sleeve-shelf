// Small behaviour pages ask for with data attributes, as the Content-Security-Policy runs no
// inline handlers such as onchange="…".
(function () {
  // A notice worth saying once stays away on this device; without storage it simply comes back.
  document.querySelectorAll("[data-put-away]").forEach(function (notice) {
    const key = "sleeve-shelf-" + notice.dataset.putAway;
    try {
      if (localStorage.getItem(key)) notice.hidden = true;
    } catch (error) {
      // Stays in view.
    }
    notice.querySelector("[data-put-away-button]").addEventListener("click", function () {
      notice.hidden = true;
      try {
        localStorage.setItem(key, "1");
      } catch (error) {
        // Gone for now, back with the next page.
      }
    });
  });

  document.addEventListener("change", function (event) {
    const field = event.target;
    // A choice that is itself the request: the list of shelves in Browse, Layout's "Go to
    // cabinet…" (whose address the server makes, so the page goes nowhere a list names).
    if (field.matches("[data-submit-on-change]") && field.value) {
      // A form that takes a while (recognising a photo) says it is busy meanwhile.
      if (field.form.hasAttribute("data-busy")) field.form.classList.add("is-busy");
      field.form.submit();
    }
  });
})();
