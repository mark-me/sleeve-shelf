// Small behaviour pages ask for with data attributes, as the Content-Security-Policy runs no
// inline handlers such as onchange="…".
(function () {
  document.addEventListener("change", function (event) {
    const field = event.target;
    // A choice that is itself the request: the list of shelves in Browse.
    if (field.matches("[data-submit-on-change]")) field.form.submit();
    // A choice that is a place to go: Layout's "Go to cabinet…".
    if (field.matches("[data-go-on-change]") && field.value) {
      const target = field.value;
      field.selectedIndex = 0;
      window.location.href = target;
    }
  });
})();
