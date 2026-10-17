// Small behaviour pages ask for with data attributes, as the Content-Security-Policy runs no
// inline handlers such as onchange="…".
(function () {
  document.addEventListener("change", function (event) {
    const field = event.target;
    // A choice that is itself the request: the list of shelves in Browse, Layout's "Go to
    // cabinet…" (whose address the server makes, so the page goes nowhere a list names).
    if (field.matches("[data-submit-on-change]") && field.value) field.form.submit();
  });
})();
