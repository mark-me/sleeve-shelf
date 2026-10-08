// Layout screen: drag blocks of albums between and within shelves, saving each move.
(function () {
  const root = document.getElementById("layout");
  const text = window.layoutText;

  // Show how full a shelf is: the meter and the line next to it.
  function showFill(shelf, albums, filled) {
    const width = parseFloat(shelf.dataset.width);
    const line = shelf.querySelector(".ss-shelf-fill");
    const meter = shelf.querySelector(".ss-meter-fill");
    line.dataset.albums = albums;
    line.dataset.filled = filled;
    const template = isNaN(width) ? text.fillNoWidth : text.fill;
    line.textContent = template
      .replace("__albums__", albums)
      .replace("__filled__", Number(filled).toFixed(1))
      .replace("__width__", isNaN(width) ? "" : width.toFixed(1));
    const share = isNaN(width) || width <= 0 ? 0 : filled / width;
    meter.style.width = Math.min(100, Math.round(share * 100)) + "%";
    shelf.classList.toggle("ss-shelf-over", share > 1);
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
      filter: "[data-split]",
      preventOnFilter: false,
      onEnd: function (event) {
        if (event.from === event.to && event.oldIndex === event.newIndex) return;
        save(event.from === event.to ? [event.to] : [event.from, event.to]);
      },
    });
  });

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
      const title = document.createElement("span");
      title.className = "ss-block-title";
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
      block.before(single);
    });
    block.remove();
  });
})();
