// Small behaviour pages ask for with data attributes, as the Content-Security-Policy runs no
// inline handlers such as onchange="…".
(function () {
  document.addEventListener("change", function (event) {
    const field = event.target;
    // A choice that is itself the request: the list of shelves in Browse.
    if (field.matches("[data-submit-on-change]")) field.form.submit();
    // A choice that is a place to go: Layout's "Go to cabinet…". Only a page of the app is
    // gone to, never a javascript: or another site's address, whatever the option holds.
    if (field.matches("[data-go-on-change]") && field.value) {
      const target = new URL(field.value, window.location.href);
      field.selectedIndex = 0;
      if (target.origin === window.location.origin) {
        window.location.assign(target.pathname + target.search + target.hash);
      }
    }
  });
})();
