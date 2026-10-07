// Light/dark theme: follows the device unless the user picked one on this device.
(function () {
  const STORAGE_KEY = "sleeve-shelf-theme";
  const system = window.matchMedia("(prefers-color-scheme: dark)");

  function stored() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (error) {
      return null;
    }
  }

  function apply() {
    const theme = stored() || (system.matches ? "dark" : "light");
    document.documentElement.setAttribute("data-bs-theme", theme);
  }

  apply();
  system.addEventListener("change", apply);

  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-theme-toggle]")) return;
    const current = document.documentElement.getAttribute("data-bs-theme");
    try {
      localStorage.setItem(STORAGE_KEY, current === "dark" ? "light" : "dark");
    } catch (error) {
      // Without storage the choice only lasts for this page.
      document.documentElement.setAttribute("data-bs-theme", current === "dark" ? "light" : "dark");
      return;
    }
    apply();
  });
})();
