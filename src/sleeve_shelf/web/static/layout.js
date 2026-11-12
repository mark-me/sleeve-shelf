// Layout screen: drag blocks of albums between and within shelves, saving each move.
(function () {
  const root = document.getElementById("layout");
  const text = window.layoutText;

  // Show how full a shelf is: the meter and the line next to it.
  // A width as the page's language writes it: "39.8" in English, "39,8" in Dutch.
  function decimal(value) {
    return Number(value).toLocaleString(document.documentElement.lang || undefined, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
  }

  function showFill(shelf, albums, filled) {
    const width = parseFloat(shelf.dataset.width);
    const line = shelf.querySelector(".ss-shelf-fill");
    const meter = shelf.querySelector(".ss-meter-fill");
    line.dataset.albums = albums;
    line.dataset.filled = filled;
    // An estimated width is shown as one, and a shelf over it is not marked as too full.
    const measured = shelf.dataset.measured === "1";
    const template = isNaN(width) ? text.fillNoWidth : measured ? text.fill : text.fillEstimated;
    line.textContent = template
      .replace("__albums__", albums)
      .replace("__filled__", decimal(filled))
      .replace("__width__", isNaN(width) ? "" : decimal(width));
    const share = isNaN(width) || width <= 0 ? 0 : filled / width;
    meter.style.width = Math.min(100, Math.round(share * 100)) + "%";
    shelf.classList.toggle("ss-shelf-over", share > 1 && measured);
    shelf.classList.toggle("ss-shelf-over-estimate", share > 1 && !measured);
  }

  root.querySelectorAll(".ss-shelf[data-shelf]").forEach(function (shelf) {
    const line = shelf.querySelector(".ss-shelf-fill");
    showFill(shelf, line.dataset.albums, line.dataset.filled);
  });

  // The album ids of a list, in the order its blocks stand.
  function contents(list) {
    return Array.from(list.querySelectorAll(".ss-block")).flatMap(function (block) {
      return block.dataset.albums.split(",").filter(Boolean).map(Number);
    });
  }

  // After a move: the way back, until the next one. The page is loaded anew afterwards, as a
  // block may have been split or joined.
  const undoBar = document.getElementById("layout-undo");
  let undoing = null;

  // On a phone the overview starts folded: it is long there, and the shelves are what is worked on.
  const glanceBox = document.getElementById("layout-glance");
  if (glanceBox && window.matchMedia("(max-width: 600px)").matches) glanceBox.open = false;

  // At a glance a cluster's name stands in its colour where there is room for it; a tap on a colour
  // shows that cluster everywhere and says what it is, a second tap shows all again.
  let chosenCluster = null;
  function nameRuns() {
    document.querySelectorAll(".ss-glance-run-name").forEach(function (name) {
      name.hidden = false;
      name.hidden = name.scrollWidth > name.parentElement.clientWidth;
    });
  }
  function chooseCluster(cluster) {
    const box = document.getElementById("layout-glance");
    const caption = box && box.querySelector("[data-glance-caption]");
    if (!box || !caption) return;
    chosenCluster = cluster;
    const runs = Array.from(box.querySelectorAll(".ss-glance-run"));
    runs.forEach(function (run) { run.classList.toggle("is-chosen", cluster !== null && run.dataset.cluster === cluster); });
    box.classList.toggle("is-choosing", cluster !== null);
    caption.classList.toggle("is-chosen", cluster !== null);
    if (cluster === null) {
      caption.textContent = caption.dataset.hint;
      return;
    }
    const mine = runs.filter(function (run) { return run.dataset.cluster === cluster; });
    const albums = mine.reduce(function (sum, run) { return sum + Number(run.dataset.albums); }, 0);
    const shelves = new Set(mine.map(function (run) { return run.dataset.glanceShelf; })).size;
    // Chosen by id, as two clusters may share a name; the name is only what is shown.
    const name = mine.length ? mine[0].dataset.clusterName : "";
    caption.textContent = caption.dataset.template
      .replace("{cluster}", name || "—").replace("{albums}", albums).replace("{shelves}", shelves);
  }
  document.addEventListener("click", function (event) {
    const run = event.target.closest(".ss-glance-run");
    if (!run) return;
    chooseCluster(chosenCluster === run.dataset.cluster ? null : run.dataset.cluster);
  });
  const glanceDetails = document.getElementById("layout-glance");
  if (glanceDetails) glanceDetails.addEventListener("toggle", nameRuns);
  window.addEventListener("resize", nameRuns);
  nameRuns();

  // All cabinets at a glance follows every move, so the whole stays in view.
  // Moves in quick succession ask for it more than once; only the latest answer is shown, so an
  // earlier one coming in last never replaces the newer overview. When it cannot be fetched it is
  // tried once more; failing again, the overview says it is out of date rather than pretend.
  let glanceAsked = 0;
  const GLANCE_RETRY_MS = 2000;
  async function refreshGlance(again) {
    const holder = document.querySelector("[data-glance]");
    if (!holder || !root.dataset.glanceUrl) return;
    const asked = again ? glanceAsked : ++glanceAsked;
    let html = null;
    try {
      const response = await fetch(root.dataset.glanceUrl);
      if (response.ok) html = await response.text();
    } catch (error) {
      // Offline or the server gone for a moment: handled below like an error answer.
    }
    if (asked !== glanceAsked) return;
    if (html === null) {
      if (!again) {
        setTimeout(function () { refreshGlance(true); }, GLANCE_RETRY_MS);
      } else {
        showGlanceStale(true);
      }
      return;
    }
    holder.replaceChildren(...fromServer(html));
    showGlanceStale(false);
    nameRuns();
    if (chosenCluster !== null) chooseCluster(chosenCluster);
  }

  // HTML the server made from its escaped templates, as nodes: parsed apart from the page, so
  // nothing in it runs, and put in place without innerHTML.
  function fromServer(html) {
    const parsed = new DOMParser().parseFromString(html, "text/html");
    return Array.from(parsed.body.childNodes, function (node) { return document.importNode(node, true); });
  }

  function showGlanceStale(stale) {
    const box = document.getElementById("layout-glance");
    const notice = box && box.querySelector("[data-glance-stale]");
    if (!box || !notice) return;
    notice.hidden = !stale;
    box.classList.toggle("is-stale", stale);
  }

  function offerUndo(shelves) {
    refreshGlance();
    undoing = shelves;
    undoBar.hidden = false;
  }

  undoBar.querySelector("button").addEventListener("click", async function () {
    undoBar.hidden = true;
    try {
      const response = await fetch(root.dataset.moveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shelves: undoing }),
      });
      if (!response.ok) throw new Error(response.status);
      window.location.reload();
    } catch (error) {
      document.getElementById("layout-error").classList.remove("d-none");
      window.scrollTo({ top: 0 });
    }
  });

  async function save(lists) {
    const shelves = {};
    lists.forEach(function (list) {
      shelves[list.dataset.list] = contents(list);
    });
    try {
      const response = await fetch(root.dataset.moveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shelves: shelves }),
      });
      if (!response.ok) throw new Error(response.status);
      const result = await response.json();
      Object.entries(result.shelves).forEach(function (entry) {
        const shelf = root.querySelector('.ss-shelf[data-shelf="' + entry[0] + '"]');
        showFill(shelf, entry[1].albums, entry[1].filled_cm);
      });
      offerUndo(result.undo);
    } catch (error) {
      // What is on screen no longer matches what is stored; say so rather than pretend.
      document.getElementById("layout-error").classList.remove("d-none");
      window.scrollTo({ top: 0 });
    }
  }

  root.querySelectorAll(".ss-blocks").forEach(function (list) {
    Sortable.create(list, {
      group: "albums",
      animation: 120,
      // The page scrolls along as soon as a drag comes near the top or bottom of
      // the window. The browser's own zone for that is only a few pixels high,
      // so Sortable's is used instead, with a wide zone and a brisk pace.
      scroll: true,
      forceAutoScrollFallback: true,
      scrollSensitivity: 160,
      scrollSpeed: 28,
      bubbleScroll: true,
      // An empty shelf takes a block that is dropped near it, not only right on it.
      emptyInsertThreshold: 32,
      filter: "[data-split], [data-send]",
      preventOnFilter: false,
      // On a touch screen a block is held a moment before it moves, so a swipe that starts
      // on a block scrolls the page instead of dragging the block. A mouse drags at once.
      delay: 300,
      delayOnTouchOnly: true,
      touchStartThreshold: 8,
      onChoose: function () {
        // A short buzz says the block is picked up, where the phone can.
        if (window.matchMedia("(pointer: coarse)").matches && navigator.vibrate) navigator.vibrate(12);
      },
      onEnd: function (event) {
        if (event.from === event.to && event.oldIndex === event.newIndex) return;
        save(event.from === event.to ? [event.to] : [event.from, event.to]);
      },
    });
  });

  // Sending a block to a shelf without dragging: pick the shelf from a list, the block goes
  // to the end of it, and the page jumps there so the exact spot can be set by dragging.
  const dialog = document.getElementById("send");
  let sending = null;

  function fillText(albums, filled, width) {
    const known = !isNaN(parseFloat(width));
    return (known ? text.fill : text.fillNoWidth)
      .replace("__albums__", albums)
      .replace("__filled__", decimal(filled))
      .replace("__width__", known ? decimal(width) : "");
  }

  function showOption(option, albums, filled) {
    const line = option.querySelector(".ss-row-place");
    if (!line) return;
    if (albums !== undefined) {
      line.dataset.albums = albums;
      line.dataset.filled = filled;
    }
    line.textContent = fillText(line.dataset.albums, line.dataset.filled, option.dataset.width);
  }

  function highlight(block) {
    block.scrollIntoView({ block: "center", behavior: "smooth" });
    block.classList.add("ss-block-moved");
    setTimeout(function () {
      block.classList.remove("ss-block-moved");
    }, 4000);
  }

  function openSend(block) {
    sending = block;
    const ids = block.dataset.albums.split(",");
    const artist = block.querySelector(".ss-block-name").textContent;
    const title = block.querySelector(".ss-block-title");
    document.getElementById("send-what").textContent = title
      ? text.sendOne.replace("__artist__", artist).replace("__title__", title.textContent)
      : text.sendWhat.replace("__artist__", artist).replace("__num__", ids.length);
    // More ways: the Move screen with this block chosen, an album on its own or else its artist.
    const more = document.getElementById("send-more");
    if (more) {
      const base = more.dataset.moveUrl;
      const chosen = ids.length === 1 || !block.dataset.artist ? "kind=album&id=" + ids[0] : "kind=artist&id=" + block.dataset.artist;
      more.href = base + (base.includes("?") ? "&" : "?") + chosen;
    }
    const here = block.closest(".ss-blocks").dataset.list;
    dialog.querySelectorAll(".ss-send-option").forEach(function (option) {
      const current = option.dataset.sendTo === here;
      option.disabled = current;
      showOption(option);
      const line = option.querySelector(".ss-row-place");
      if (current && line) line.textContent = text.current;
    });
    bootstrap.Modal.getOrCreateInstance(dialog).show();
  }

  root.addEventListener("click", function (event) {
    const button = event.target.closest("[data-send]");
    if (button) openSend(button.closest(".ss-block"));
  });
  // The same list on a right-click, for those who look for it there.
  root.addEventListener("contextmenu", function (event) {
    const block = event.target.closest(".ss-block");
    if (!block) return;
    event.preventDefault();
    openSend(block);
  });

  dialog.addEventListener("click", async function (event) {
    const option = event.target.closest(".ss-send-option");
    if (!option || !sending) return;
    const block = sending;
    const ids = block.dataset.albums.split(",").map(Number);
    try {
      const response = await fetch(root.dataset.sendUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ albums: ids, shelf: Number(option.dataset.sendTo) }),
      });
      if (!response.ok) throw new Error(response.status);
      const result = await response.json();
      bootstrap.Modal.getOrCreateInstance(dialog).hide();
      const list = root.querySelector('.ss-blocks[data-list="' + option.dataset.sendTo + '"]');
      if (!list) {
        // The shelf is in another room: go to its tab, and find the block there.
        window.location.href = option.dataset.url + "#album-" + ids[0];
        return;
      }
      list.append(block);
      offerUndo(result.undo);
      Object.entries(result.shelves).forEach(function (entry) {
        const shelf = root.querySelector('.ss-shelf[data-shelf="' + entry[0] + '"]');
        if (shelf) showFill(shelf, entry[1].albums, entry[1].filled_cm);
        const listed = dialog.querySelector('.ss-send-option[data-send-to="' + entry[0] + '"]');
        if (listed) showOption(listed, entry[1].albums, entry[1].filled_cm);
      });
      // Only once the list is gone: while it is open the page behind it does not scroll.
      dialog.addEventListener("hidden.bs.modal", function () { highlight(block); }, { once: true });
    } catch (error) {
      bootstrap.Modal.getOrCreateInstance(dialog).hide();
      document.getElementById("layout-error").classList.remove("d-none");
      window.scrollTo({ top: 0 });
    }
  });

  // Arriving from another room after a block was sent here: show where it went.
  const arrived = /^#album-(\d+)$/.exec(window.location.hash);
  if (arrived) {
    const block = Array.from(root.querySelectorAll(".ss-block")).find(function (candidate) {
      return candidate.dataset.albums.split(",").includes(arrived[1]);
    });
    if (block) highlight(block);
  }

  // Splitting a block puts each of its albums in a block of its own; nothing moves yet.
  root.addEventListener("click", function (event) {
    const button = event.target.closest("[data-split]");
    if (!button) return;
    const block = button.closest(".ss-block");
    const ids = block.dataset.albums.split(",");
    const titles = button.dataset.titles.split("|");
    const covers = (button.dataset.covers || "").split("|");
    const link = block.querySelector(".ss-block-name");
    ids.forEach(function (id, index) {
      const single = document.createElement("li");
      single.className = "ss-block";
      single.dataset.albums = id;
      const name = link.cloneNode(true);
      const title = document.createElement("a");
      title.className = "ss-block-title";
      title.href = button.dataset.albumUrl.replace(/0$/, id);
      title.draggable = false;
      title.textContent = titles[index] || "";
      if (covers[index]) {
        const cover = document.createElement("img");
        cover.className = "ss-cover";
        cover.src = covers[index];
        cover.alt = "";
        cover.width = cover.height = 28;
        cover.referrerPolicy = "no-referrer";
        single.append(cover);
      }
      single.append(name, title);
      // Each single album can be sent to a shelf on its own, like the block it came from.
      const send = block.querySelector("[data-send]");
      if (send) single.append(send.cloneNode(true));
      block.before(single);
    });
    block.remove();
  });
})();
