// Connections: draws the network of artists with Cytoscape, from the screen's JSON. Around one
// artist it shows the artists tied to it, one or two steps out; otherwise every artist with a
// tie. The switches show or hide each kind of tie, in the network and in the list below it.
// A first tap on an artist lights up its ties, a second puts it in the middle.
(function () {
  const box = document.getElementById("ss-network");
  if (!box) return;
  const infoText = document.querySelector("[data-info-text]");
  const centreLink = document.querySelector("[data-network-centre]");
  const albumsLink = document.querySelector("[data-network-albums]");
  const hint = infoText.textContent;
  if (!window.cytoscape) {
    // The library did not load: say so, rather than an empty network with directions for it.
    infoText.textContent = box.dataset.failed;
    document.querySelectorAll("[data-network-fit], [data-network-full]").forEach((button) => (button.hidden = true));
    return;
  }
  const switches = Array.from(document.querySelectorAll("input[data-tie]"));
  const TIES = ["name", "member", "billing", "family", "credit", "session", "songs", "label"];
  const centre = box.dataset.artist ? Number(box.dataset.artist) : null;
  const steps = Number(box.dataset.steps || 1);
  // Ties that say two artists share something, rather than that they know each other.
  const LOOSE = ["songs", "label"];
  // The way to another artist, as the artists along it: then the network shows only that.
  const wayIds = box.dataset.way ? box.dataset.way.split(",").map(Number) : null;
  const MAX_FIT_ZOOM = 1.25;
  let network = null;
  let clusterColours = new Map();
  let clusterNames = new Map();
  let cy = null;
  // The artist tapped once, whose ties are lit up.
  let selected = null;
  const legend = document.querySelector("[data-network-legend]");
  // The switches go along in the links once the user has switched one; until then each page
  // starts as it does by default.
  let keepTies = new URL(window.location.href).searchParams.has("ties");

  function active() {
    return new Set(switches.filter((input) => input.checked).map((input) => input.dataset.tie));
  }

  function tieName(tie) {
    const input = switches.find((s) => s.dataset.tie === tie);
    return input ? input.parentElement.querySelector("[data-tie-label]").textContent.trim() : tie;
  }

  function colour(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function albums(count) {
    return count === 1 ? box.dataset.albumsOne : box.dataset.albumsMany.replace("{n}", count);
  }

  // Each cluster its own colour, whichever others stand beside it in a view. What is seen
  // together mostly stands together on the shelves, so neighbours must differ most: each next
  // cluster turns the hue by the golden angle, and lightness goes round in three steps.
  function colourClusters() {
    const LIGHTNESS = [38, 52, 66];
    network.clusters.forEach(([id, name], index) => {
      const hue = Math.round((index * 137.508) % 360);
      clusterColours.set(id, "hsl(" + hue + ", 62%, " + LIGHTNESS[index % 3] + "%)");
      clusterNames.set(id, name);
    });
  }

  function elements() {
    const shown = active();
    const links = network.links
      .map(([one, other, ties, songs, record, labels]) => ({ one, other, ties: ties.filter((t) => shown.has(t)), songs, record, labels }))
      .filter((link) => link.ties.length);
    const looseOnly = (link) => link.ties.every((tie) => LOOSE.includes(tie));
    const depth = new Map();
    if (wayIds) {
      wayIds.forEach((id, index) => depth.set(id, index));
    } else if (centre !== null) {
      // A song or label leads only from the artist in the middle: followed further, they
      // would tie in most of the collection.
      const next = new Map();
      const add = (one, other, songs) => {
        if (!next.has(one)) next.set(one, []);
        next.get(one).push([other, songs]);
      };
      links.forEach((link) => {
        add(link.one, link.other, looseOnly(link));
        add(link.other, link.one, looseOnly(link));
      });
      depth.set(centre, 0);
      let edge = [centre];
      for (let step = 1; step <= steps; step++) {
        const found = [];
        edge.forEach((id) =>
          (next.get(id) || []).forEach(([other, songs]) => {
            if (songs && step > 1) return;
            if (!depth.has(other)) {
              depth.set(other, step);
              found.push(other);
            }
          })
        );
        edge = found;
      }
    } else {
      links.forEach((link) => {
        depth.set(link.one, 0);
        depth.set(link.other, 0);
      });
    }
    const stepOut = (link) => Math.abs(depth.get(link.one) - depth.get(link.other)) === 1;
    // Reached by a closer tie than a song or label: such an artist stands on the inner ring of its step.
    const close = new Set();
    links.forEach((link) => {
      if (centre === null || looseOnly(link) || !depth.has(link.one) || !depth.has(link.other) || !stepOut(link)) return;
      close.add(depth.get(link.one) > depth.get(link.other) ? link.one : link.other);
    });
    const nodes = network.artists
      .filter(([id]) => depth.has(id))
      .map(([id, name, count, cluster, picture, borrowed]) => ({
        data: {
          id: String(id),
          name: name,
          albums: count,
          cluster: cluster,
          colour: clusterColours.get(cluster) || colour("--ss-muted"),
          // Around one artist a picture is recognised sooner than a name; over the whole
          // collection hundreds of them would be specks.
          picture: centre !== null && picture ? picture : null,
          borrowed: Boolean(centre !== null && picture && borrowed),
          size: Math.min((centre !== null && picture ? 34 : 14) + 6 * Math.sqrt(count), 64),
          ring: 2 * (steps + 1 - depth.get(id)) + (close.has(id) ? 1 : 0),
        },
        classes: [
          id === centre ? "centre" : "",
          centre !== null && picture ? "picture" : "",
          centre !== null && picture && borrowed ? "borrowed" : "",
          id < 0 ? "musician" : "",
        ].join(" "),
      }));
    // Around an artist songs and labels are drawn only from the artist in the middle, as they
    // lead only from there; between the others they would tangle the rings.
    const onTheWay = (link) => Math.abs(wayIds.indexOf(link.one) - wayIds.indexOf(link.other)) === 1;
    const edges = links
      .filter((link) => depth.has(link.one) && depth.has(link.other))
      .filter((link) =>
        wayIds ? onTheWay(link) : centre === null || !looseOnly(link) || link.one === centre || link.other === centre
      )
      .map((link) => ({
        data: {
          id: link.one + "-" + link.other,
          source: String(link.one),
          target: String(link.other),
          ties: link.ties,
          songs: link.ties.includes("songs") ? link.songs : [],
          record: link.ties.includes("credit") || link.ties.includes("session") ? link.record : [],
          labels: link.ties.includes("label") ? link.labels : [],
          width: link.ties[0] === "songs" ? 1 + Math.min(link.songs.length, 6) * 0.5 : link.ties[0] === "label" ? 1.5 : link.ties[0] === "session" ? 2 : 2.5,
        },
        classes: link.ties[0],
      }));
    return nodes.concat(edges);
  }

  function style() {
    const lines = TIES.map((tie) => ({
      selector: "edge." + tie,
      style: {
        "line-color": colour("--ss-tie-" + tie),
        "line-style": tie === "name" ? "dotted" : tie === "family" ? "dashed" : "solid",
      },
    }));
    return [
      {
        selector: "node",
        style: {
          "background-color": "data(colour)",
          width: "data(size)",
          height: "data(size)",
          label: "data(name)",
          "font-size": 11,
          color: colour("--ss-text"),
          "text-valign": "bottom",
          "text-margin-y": 4,
          // "The Miles Davis Quintet Together With Gil Evans And His Orchestra" on a few lines.
          "text-wrap": "wrap",
          "text-max-width": 110,
          "text-outline-color": colour("--ss-surface"),
          "text-outline-width": 2,
          // Over the whole collection the names come when zoomed in, or they hide the lines.
          "min-zoomed-font-size": centre === null ? 9 : 0,
          "border-width": 1,
          "border-color": colour("--ss-surface"),
          "transition-property": "opacity",
          "transition-duration": "150ms",
        },
      },
      {
        // The picture fills the point; the cluster's colour stays as its ring.
        selector: "node.picture",
        style: {
          "background-image": "data(picture)",
          "background-fit": "cover",
          "background-clip": "node",
          "border-width": 3,
          "border-color": "data(colour)",
        },
      },
      // A musician without an album of their own is no artist: another shape, as no cluster.
      { selector: "node.musician", style: { shape: "diamond" } },
      // A picture borrowed from an artist it names: the ring says so.
      { selector: "node.borrowed", style: { "border-style": "dashed" } },
      { selector: "node.centre", style: { "border-width": 4, "border-color": colour("--ss-accent"), "font-weight": 600 } },
      { selector: "edge", style: { width: "data(width)", "curve-style": "straight", opacity: 0.85 } },
    ]
      .concat(lines)
      .concat([
        { selector: "edge.songs, edge.label", style: { opacity: 0.6 } },
        // What is lit up stands out; the rest fades, names and all.
        { selector: "node.chosen", style: { "border-width": 4, "border-color": colour("--ss-text"), "font-weight": 600, "z-index": 10 } },
        { selector: "node.lit", style: { "min-zoomed-font-size": 0, "z-index": 9 } },
        { selector: ".faded", style: { opacity: 0.12, "text-opacity": 0 } },
      ]);
  }

  function layout() {
    if (wayIds) {
      // One step below the other, from the artist in the middle to the other one.
      return { name: "breadthfirst", roots: [String(wayIds[0])], spacingFactor: 1.1, animate: false, padding: 24 };
    }
    if (centre !== null) {
      return {
        name: "concentric",
        concentric: (node) => node.data("ring"),
        levelWidth: () => 1,
        minNodeSpacing: 50,
        animate: false,
        padding: 24,
      };
    }
    return { name: "cose", animate: false, randomize: true, nodeRepulsion: () => 8000, idealEdgeLength: () => 60, padding: 24 };
  }

  function withTies(href) {
    const url = new URL(href, window.location.href);
    if (keepTies) url.searchParams.set("ties", TIES.filter((tie) => active().has(tie)).join(","));
    return url.pathname + url.search + url.hash;
  }

  function centreUrl(id) {
    let url = box.dataset.centreUrl.replace("artist=0", "artist=" + id);
    if (steps === 2) url += "&steps=2";
    return withTies(url);
  }

  // Every link to this screen, and the address of the page itself, take the switches along.
  function carryTies() {
    keepTies = true;
    document.querySelectorAll('a[href^="/connections/"]').forEach((link) => {
      link.setAttribute("href", withTies(link.getAttribute("href")));
    });
    const hidden = document.querySelector('form[role="search"] input[name="ties"]');
    const value = TIES.filter((tie) => active().has(tie)).join(",");
    if (hidden) hidden.value = value;
    else {
      const field = document.createElement("input");
      field.type = "hidden";
      field.name = "ties";
      field.value = value;
      document.querySelector('form[role="search"]').append(field);
    }
    window.history.replaceState(null, "", withTies(window.location.href));
  }

  // The line under the network; with an artist, the way to put it in the middle and to its
  // albums in the list below.
  function say(text, artistId) {
    infoText.textContent = text;
    const offered = artistId !== undefined && artistId !== null && artistId !== centre;
    centreLink.hidden = !offered;
    if (offered) centreLink.href = centreUrl(artistId);
    const row = offered ? document.getElementById("tie-" + artistId) : null;
    albumsLink.hidden = !(row && row.querySelector("[data-tie-albums]"));
    if (!albumsLink.hidden) albumsLink.href = "#tie-" + artistId;
    document.querySelectorAll(".ss-row-current").forEach((other) => other.classList.remove("ss-row-current"));
    if (row) row.classList.add("ss-row-current");
  }

  function describe(node, offer) {
    const data = node.data();
    const parts = [data.name, Number(data.id) < 0 ? box.dataset.musician : clusterNames.get(data.cluster) || box.dataset.noCluster, albums(data.albums)];
    if (data.borrowed) parts.push(box.dataset.borrowed);
    const text = parts.join(" · ");
    say(text, offer ? Number(data.id) : null);
  }

  function describeLine(edge) {
    const data = edge.data();
    const names = [data.source, data.target].map((id) => cy.getElementById(id).data("name"));
    let text = names.join(" — ") + ": " + data.ties.map(tieName).join(", ");
    if (data.songs.length) {
      text += " · ♪ " + data.songs.slice(0, 8).join(", ") + (data.songs.length > 8 ? " …" : "");
    }
    data.record.slice(0, 4).forEach(([name, roles, album]) => {
      text += " · " + name + ": " + roles + " (" + album + ")";
    });
    if (data.record.length > 4) text += " …";
    if (data.labels.length) text += " · " + box.dataset.labelWord + " " + data.labels.join(", ");
    say(text);
  }

  // Light up some of the network and fade the rest; nothing given lights up everything.
  function light(kept, chosen) {
    cy.batch(() => {
      cy.elements().removeClass("faded lit chosen");
      if (!kept) return;
      cy.elements().not(kept).addClass("faded");
      kept.nodes().addClass("lit");
      if (chosen) chosen.addClass("chosen");
    });
  }

  // Over the whole collection what lights up is a speck: zoom to it.
  function zoomTo(kept) {
    if (centre !== null) return;
    cy.stop();
    cy.animate(
      { fit: { eles: kept, padding: 60 } },
      {
        duration: 300,
        complete: () => {
          if (cy.zoom() > MAX_FIT_ZOOM) cy.zoom({ level: MAX_FIT_ZOOM, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
        },
      }
    );
  }

  function select(node) {
    selected = node.id();
    pressLegend(null);
    light(node.closedNeighborhood(), node);
    zoomTo(node.closedNeighborhood());
    describe(node, true);
  }

  function unselect() {
    selected = null;
    pressLegend(null);
    light(null);
    say(hint);
  }

  // The clusters of the artists in view, in their order on the shelves.
  function fillLegend() {
    const shown = new Set(cy.nodes().map((node) => node.data("cluster")));
    legend.replaceChildren();
    network.clusters
      .filter(([id]) => shown.has(id))
      .forEach(([id, name]) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "ss-legend-item";
        item.dataset.cluster = id;
        item.setAttribute("aria-pressed", "false");
        const dot = document.createElement("span");
        dot.className = "ss-legend-dot";
        dot.style.background = clusterColours.get(id);
        item.append(dot, document.createTextNode(name));
        item.addEventListener("click", () => lightCluster(id, item));
        legend.append(item);
      });
    legend.closest("details").hidden = !legend.children.length;
  }

  function pressLegend(item) {
    legend.querySelectorAll("[aria-pressed]").forEach((other) => other.setAttribute("aria-pressed", String(other === item)));
  }

  function lightCluster(id, item) {
    if (item.getAttribute("aria-pressed") === "true") return unselect();
    selected = null;
    const members = cy.nodes().filter((node) => node.data("cluster") === id);
    light(members.union(members.edgesWith(members)));
    zoomTo(members);
    pressLegend(item);
    const count = members.length === 1 ? box.dataset.artistsOne : box.dataset.artistsMany.replace("{n}", members.length);
    say(clusterNames.get(id) + " · " + count);
  }

  // Fit the network on the screen, but a handful of artists not larger than life.
  function fit() {
    cy.fit(undefined, 24);
    if (cy.zoom() > MAX_FIT_ZOOM) {
      cy.zoom(MAX_FIT_ZOOM);
      cy.center();
    }
  }

  function filterList() {
    const shown = active();
    document.querySelectorAll("[data-ties]").forEach((row) => {
      row.hidden = !row.dataset.ties.split(" ").some((tie) => shown.has(tie));
    });
  }

  function draw() {
    const items = elements();
    if (!cy) {
      cy = cytoscape({ container: box, style: style(), minZoom: 0.05, maxZoom: 4 });
      cy.on("tap", "node", (event) => {
        const node = event.target;
        // A second tap on the artist lit up puts it in the middle.
        if (selected === node.id() && Number(node.id()) !== centre) {
          window.location.href = centreUrl(node.id());
          return;
        }
        select(node);
      });
      cy.on("tap", "edge", (event) => {
        selected = null;
        pressLegend(null);
        light(event.target.union(event.target.connectedNodes()));
        describeLine(event.target);
      });
      cy.on("tap", (event) => {
        if (event.target === cy) unselect();
      });
      // With a mouse: who it is, without lighting anything up.
      cy.on("mouseover", "node", (event) => {
        if (selected === null) describe(event.target, false);
      });
    }
    selected = null;
    cy.elements().remove();
    cy.add(items);
    say(cy.edges().length ? hint : box.dataset.empty);
    fillLegend();
    const placing = cy.layout(layout());
    placing.one("layoutstop", fit);
    placing.run();
  }

  switches.forEach((input) =>
    input.addEventListener("change", () => {
      filterList();
      carryTies();
      // The way goes along the ties switched on: worked out again for the new ones. The list
      // holds who shares only a label when asked for: fetched again too.
      if (wayIds || (centre !== null && input.dataset.tie === "label")) window.location.reload();
      else if (network) draw();
    })
  );
  filterList();

  // The albums of the artist lit up, opened in the list.
  albumsLink.addEventListener("click", () => {
    const row = document.querySelector(albumsLink.getAttribute("href"));
    const albums = row && row.querySelector("[data-tie-albums]");
    if (albums) albums.open = true;
    if (frame.classList.contains("ss-network-full")) full(false);
  });

  // The way here: the artists put in the middle one after another in this tab. Going back to
  // one of them cuts the way off there.
  const TRAIL_KEY = "sleeve-shelf-connections-trail";
  const TRAIL_LENGTH = 8;
  const trailBox = document.querySelector("[data-network-trail]");

  function readTrail() {
    try {
      return JSON.parse(sessionStorage.getItem(TRAIL_KEY)) || [];
    } catch (error) {
      return [];
    }
  }

  function showTrail() {
    let trail = readTrail();
    if (centre !== null) {
      const index = trail.findIndex(([id]) => id === centre);
      trail = index >= 0 ? trail.slice(0, index + 1) : trail.concat([[centre, box.dataset.artistName]]);
      trail = trail.slice(-TRAIL_LENGTH);
      try {
        sessionStorage.setItem(TRAIL_KEY, JSON.stringify(trail));
      } catch (error) {
        // Without storage there is no way to show; the page works the same.
      }
    }
    trailBox.replaceChildren();
    if (trail.length < 2) return;
    trail.forEach(([id, name], index) => {
      if (index) {
        const sep = document.createElement("span");
        sep.className = "ss-trail-sep";
        sep.setAttribute("aria-hidden", "true");
        sep.textContent = "›";
        trailBox.append(sep);
      }
      if (id === centre) {
        const here = document.createElement("strong");
        here.textContent = name;
        here.setAttribute("aria-current", "page");
        trailBox.append(here);
      } else {
        const link = document.createElement("a");
        link.href = centreUrl(id);
        link.textContent = name;
        trailBox.append(link);
      }
    });
    trailBox.hidden = false;
  }

  showTrail();

  // While typing: the artists of the network. One in view is lit up on the map; another
  // opens its connections. Enter still searches as before.
  const search = document.getElementById("search");
  const suggest = document.querySelector("[data-network-suggest]");
  const SUGGESTED = 8;

  function plain(text) {
    return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  function suggestFor(text) {
    suggest.replaceChildren();
    const words = plain(text).split(/\s+/).filter(Boolean);
    if (!network || !words.length) {
      suggest.hidden = true;
      return;
    }
    const inView = (id) => cy && cy.getElementById(String(id)).nonempty();
    const found = network.artists
      .filter(([, name]) => words.every((word) => plain(name).includes(word)))
      .sort((a, b) => Number(inView(b[0])) - Number(inView(a[0])) || a[1].localeCompare(b[1]))
      .slice(0, SUGGESTED);
    found.forEach(([id, name, , cluster]) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "ss-suggest-row";
      const label = document.createElement("span");
      label.textContent = name;
      const note = document.createElement("span");
      note.className = "ss-muted small";
      note.textContent = inView(id) ? clusterNames.get(cluster) || box.dataset.noCluster : suggest.dataset.notInView;
      row.append(label, note);
      row.addEventListener("click", () => {
        suggest.hidden = true;
        if (inView(id)) {
          select(cy.getElementById(String(id)));
          box.scrollIntoView({ block: "nearest", behavior: "smooth" });
        } else {
          window.location.href = centreUrl(id);
        }
      });
      suggest.append(row);
    });
    suggest.hidden = !found.length;
  }

  search.addEventListener("input", () => suggestFor(search.value));
  search.addEventListener("keydown", (event) => {
    if (event.key === "Escape") suggest.hidden = true;
  });

  const fitButton = document.querySelector("[data-network-fit]");
  if (fitButton) fitButton.addEventListener("click", () => cy && fit());

  // Full screen: the network with its line and legend over the whole page, until closed.
  const frame = document.getElementById("ss-network-frame");
  const fullButton = document.querySelector("[data-network-full]");

  function full(on) {
    frame.classList.toggle("ss-network-full", on);
    document.body.classList.toggle("ss-no-scroll", on);
    fullButton.textContent = on ? fullButton.dataset.close : fullButton.dataset.open;
    fullButton.setAttribute("aria-pressed", String(on));
    if (cy) {
      cy.resize();
      fit();
    }
  }

  fullButton.addEventListener("click", () => full(!frame.classList.contains("ss-network-full")));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && frame.classList.contains("ss-network-full")) full(false);
  });

  // The light and dark theme have colours of their own.
  new MutationObserver(() => cy && cy.style(style())).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-bs-theme"],
  });

  fetch(box.dataset.url, { headers: { Accept: "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error(response.statusText);
      return response.json();
    })
    .then((data) => {
      network = data;
      colourClusters();
      draw();
    })
    .catch(() => {
      say(box.dataset.failed);
    });
})();
