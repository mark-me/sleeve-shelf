// Measure shelves: saving a width keeps the page where it is. The row says the new width and room,
// the count at the top goes up, and the next shelf's field is ready to type in. Without script the
// form simply saves and comes back.
(function () {
  const forms = Array.from(document.querySelectorAll("form[data-measure]"));
  forms.forEach(function (form, index) {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      const button = form.querySelector("button");
      button.disabled = true;
      let answer;
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { Accept: "application/json" },
        });
        answer = await response.json();
      } catch (error) {
        form.submit(); // Offline or something unexpected: the plain way.
        return;
      } finally {
        button.disabled = false;
      }
      form.classList.toggle("ss-measure-error", Boolean(answer.error));
      if (answer.error) {
        form.querySelector("[data-measure-status]").textContent = answer.error;
        return;
      }
      // The row as the server made it from its escaped template, parsed apart from the page.
      const parsed = new DOMParser().parseFromString(answer.status, "text/html");
      form.querySelector("[data-measure-status]").replaceChildren(
        ...Array.from(parsed.body.childNodes, function (node) { return document.importNode(node, true); })
      );
      document.querySelector("[data-measured-count]").textContent = answer.measured;
      document.querySelector("[data-measured-meter]").style.width =
        Math.round((100 * answer.measured) / answer.shelves) + "%";
      const next = forms[index + 1];
      if (next) {
        const field = next.querySelector("input[name=width_cm]");
        field.focus();
        next.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    });
  });
})();
