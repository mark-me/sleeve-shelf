// Connections: draws the network of artists with Cytoscape, from the screen's JSON. Around one
// artist it shows the artists tied to it, one or two steps out; otherwise every artist with a
// tie. The switches show or hide each kind of tie, in the network and in the list below it.
// A first tap on an artist lights up its ties, a second puts it in the middle.
(function () {
  const box = document.getElementById("ss-network");
  if (!box) return;
  const infoText = document.querySelector("[data-info-text]");
  const centreLink = document.querySelector("[data-network-centre]");
  const hint = infoText.textContent;
  if (!window.cytoscape) {
    // The library did not load: say so, rather than an empty network with directions for it.
    infoText.textContent = box.dataset.failed;
    document.querySelectorAll("[data-network-fit], [data-network-full]").forEach((button) => (button.hidden = true));
    return;
  }
  const switches = Array.from(document.querySelectorAll("input[data-tie]"));
  const TIES = ["name", "member", "billing", "family", "songs"];
  const centre = box.dataset.artist ? Number(box.dataset.artist) : null;
  const steps = Number(box.dataset.steps || 1);
  const MAX_FIT_ZOOM = 1.25;
  let network = null;
  let clusterColours = new Map();
  let clusterNames = new Map();
  let cy = null;
  // The artist tapped once, whose ties are lit up.
  let selected = null;
  const legend = document.querySelector("[data-network-legend]");

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

  // Clusters next to each other on the shelves get colours next to each other, one lighter
  // and one darker in turn, so neighbours can still be told apart.
  function colourClusters() {
    const count = Math.max(network.clusters.length, 1);
    network.clusters.forEach(([id, name], index) => {
      const lightness = index % 2 ? 40 : 62;
      clusterColours.set(id, "hsl(" + Math.round((index / count) * 330) + ", 60%, " + lightness + "%)");
      clusterNames.set(id, name);
    });
  }

  function elements() {
    const shown = active();
    const links = network.links
      .map(([one, other, ties, songs]) => ({ one, other, ties: ties.filter((t) => shown.has(t)), songs }))
      .filter((link) => link.ties.length);
    const songsOnly = (link) => link.ties.every((tie) => tie === "songs");
    const depth = new Map();
    if (centre !== null) {
      // A song leads only from the artist in the middle: followed further, songs would tie
      // in most of the collection.
      const next = new Map();
      const add = (one, other, songs) => {
        if (!next.has(one)) next.set(one, []);
        next.get(one).push([other, songs]);
      };
      links.forEach((link) => {
        add(link.one, link.other, songsOnly(link));
        add(link.other, link.one, songsOnly(link));
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
    // Reached by a closer tie than a song: such an artist stands on the inner ring of its step.
    const close = new Set();
    links.forEach((link) => {
      if (centre === null || songsOnly(link) || !depth.has(link.one) || !depth.has(link.other) || !stepOut(link)) return;
      close.add(depth.get(link.one) > depth.get(link.other) ? link.one : link.other);
    });
    const nodes = network.artists
      .filter(([id]) => depth.has(id))
      .map(([id, name, count, cluster, picture]) => ({
        data: {
          id: String(id),
          name: name,
          albums: count,
          cluster: cluster,
          colour: clusterColours.get(cluster) || colour("--ss-muted"),
          // Around one artist a picture is recognised sooner than a name; over the whole
          // collection hundreds of them would be specks.
          picture: centre !== null && picture ? picture : null,
          size: Math.min((centre !== null && picture ? 34 : 14) + 6 * Math.sqrt(count), 64),
          ring: 2 * (steps + 1 - depth.get(id)) + (close.has(id) ? 1 : 0),
        },
        classes: [id === centre ? "centre" : "", centre !== null && picture ? "picture" : ""].join(" "),
      }));
    // Around an artist songs are drawn only from the artist in the middle, as they lead only
    // from there; between the others they would tangle the rings.
    const edges = links
      .filter((link) => depth.has(link.one) && depth.has(link.other))
      .filter((link) => centre === null || !songsOnly(link) || link.one === centre || link.other === centre)
      .map((link) => ({
        data: {
          id: link.one + "-" + link.other,
          source: String(link.one),
          target: String(link.other),
          ties: link.ties,
          songs: link.ties.includes("songs") ? link.songs : [],
          width: link.ties[0] === "songs" ? 1 + Math.min(link.songs.length, 6) * 0.5 : 2.5,
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
      { selector: "node.centre", style: { "border-width": 4, "border-color": colour("--ss-accent"), "font-weight": 600 } },
      { selector: "edge", style: { width: "data(width)", "curve-style": "straight", opacity: 0.85 } },
    ]
      .concat(lines)
      .concat([
        { selector: "edge.songs", style: { opacity: 0.6 } },
        // What is lit up stands out; the rest fades, names and all.
        { selector: "node.chosen", style: { "border-width": 4, "border-color": colour("--ss-text"), "font-weight": 600, "z-index": 10 } },
        { selector: "node.lit", style: { "min-zoomed-font-size": 0, "z-index": 9 } },
        { selector: ".faded", style: { opacity: 0.12, "text-opacity": 0 } },
      ]);
  }

  function layout() {
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

  function centreUrl(id) {
    let url = box.dataset.centreUrl.replace("artist=0", "artist=" + id);
    if (steps === 2) url += "&steps=2";
    return url;
  }

  // The line under the network; with an artist, the way to put it in the middle.
  function say(text, artistId) {
    infoText.textContent = text;
    const offered = artistId !== undefined && artistId !== null && artistId !== centre;
    centreLink.hidden = !offered;
    if (offered) centreLink.href = centreUrl(artistId);
  }

  function describe(node, offer) {
    const data = node.data();
    const text = [data.name, clusterNames.get(data.cluster) || box.dataset.noCluster, albums(data.albums)].join(" · ");
    say(text, offer ? Number(data.id) : null);
  }

  function describeLine(edge) {
    const data = edge.data();
    const names = [data.source, data.target].map((id) => cy.getElementById(id).data("name"));
    let text = names.join(" — ") + ": " + data.ties.map(tieName).join(", ");
    if (data.songs.length) {
      text += " · ♪ " + data.songs.slice(0, 8).join(", ") + (data.songs.length > 8 ? " …" : "");
    }
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
      if (network) draw();
    })
  );
  filterList();

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
