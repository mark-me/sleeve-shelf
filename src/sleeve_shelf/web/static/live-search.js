// Search while typing: a form marked data-live-search fetches its page anew after a short
// pause and puts the new page in place around the form, so the field keeps its focus and
// caret. Without JavaScript, or when the new page has no such form, Enter works as before.
(function () {
  const PAUSE_MS = 250;

  document.querySelectorAll("form[data-live-search]").forEach(function (form) {
    const input = form.querySelector('input[type="search"]');
    if (!input) return;
    let timer = null;
    let latest = null;

    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(search, PAUSE_MS);
    });

    async function search() {
      const url = new URL(form.action, window.location.href);
      const fields = new URLSearchParams(new FormData(form));
      // An empty search leaves no "?q=" behind in the address.
      for (const [name, value] of Array.from(fields)) if (!value) fields.delete(name);
      url.search = fields.toString();
      if (latest) latest.abort();
      const controller = (latest = new AbortController());
      let html;
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) return;
        html = await response.text();
      } catch (error) {
        return; // Overtaken by the next keystroke, or offline: Enter still works.
      }
      if (controller !== latest) return;
      const page = new DOMParser().parseFromString(html, "text/html");
      if (!swapAround(form, page)) {
        window.location.href = url;
        return;
      }
      document.title = page.title;
      history.replaceState(null, "", url);
    }
  });

  // Replace everything in <main> except the form itself, level by level: at each level the
  // siblings before and after the form's branch come from the new page.
  function swapAround(form, page) {
    const main = document.querySelector("main");
    const newForm = page.querySelector("form[data-live-search]");
    const newMain = page.querySelector("main");
    if (!main || !newForm || !newMain) return false;

    const branch = [];
    for (let node = form; node !== main; node = node.parentElement) {
      if (!node) return false;
      branch.push(node);
    }
    const newBranch = [];
    for (let node = newForm; node !== newMain; node = node.parentElement) {
      if (!node) return false;
      newBranch.push(node);
    }
    // The new page has to keep the form at the same depth, in the same kind of container.
    if (branch.length !== newBranch.length) return false;
    for (let i = 1; i < branch.length; i++) {
      if (branch[i].className !== newBranch[i].className) return false;
    }

    for (let i = 0; i < branch.length; i++) {
      const keep = branch[i];
      const fresh = newBranch[i];
      const parent = keep.parentElement;
      const before = [];
      const after = [];
      let past = false;
      for (const child of Array.from(fresh.parentElement.childNodes)) {
        if (child === fresh) past = true;
        else (past ? after : before).push(document.importNode(child, true));
      }
      while (keep.previousSibling) keep.previousSibling.remove();
      while (keep.nextSibling) keep.nextSibling.remove();
      keep.before(...before);
      keep.after(...after);
      // The container itself may differ in its attributes (a hidden header, say).
      if (i > 0) {
        for (const attribute of Array.from(fresh.attributes)) keep.setAttribute(attribute.name, attribute.value);
      }
      if (parent === main) break;
    }
    return true;
  }
})();
