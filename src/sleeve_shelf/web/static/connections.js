// Connections: draws the network of artists with Cytoscape, from the screen's JSON. Around one
// artist it shows the artists tied to it, one or two steps out; otherwise every artist with a
// tie. The switches show or hide each kind of tie, in the network and in the list below it.
(function () {
  const box = document.getElementById("ss-network");
  if (!box) return;
  const info = document.getElementById("ss-network-info");
  if (!window.cytoscape) {
    // The library did not load: say so, rather than an empty network with directions for it.
    info.textContent = box.dataset.failed;
    const fitButton = document.querySelector("[data-network-fit]");
    if (fitButton) fitButton.hidden = true;
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

  // Clusters next to each other on the shelves get colours next to each other.
  function colourClusters() {
    const count = Math.max(network.clusters.length, 1);
    network.clusters.forEach(([id, name], index) => {
      clusterColours.set(id, "hsl(" + Math.round((index / count) * 330) + ", 55%, 52%)");
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
      .concat([{ selector: "edge.songs", style: { opacity: 0.6 } }]);
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

  function describe(node) {
    const data = node.data();
    info.textContent = [data.name, clusterNames.get(data.cluster) || box.dataset.noCluster, albums(data.albums)].join(" · ");
  }

  function describeLine(edge) {
    const data = edge.data();
    const names = [data.source, data.target].map((id) => cy.getElementById(id).data("name"));
    let text = names.join(" — ") + ": " + data.ties.map(tieName).join(", ");
    if (data.songs.length) {
      text += " · ♪ " + data.songs.slice(0, 8).join(", ") + (data.songs.length > 8 ? " …" : "");
    }
    info.textContent = text;
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
        const id = Number(event.target.id());
        if (id === centre) return describe(event.target);
        let url = box.dataset.centreUrl.replace("artist=0", "artist=" + id);
        if (steps === 2) url += "&steps=2";
        window.location.href = url;
      });
      cy.on("mouseover", "node", (event) => describe(event.target));
      cy.on("tap", "edge", (event) => describeLine(event.target));
    }
    cy.elements().remove();
    cy.add(items);
    if (!cy.edges().length) info.textContent = box.dataset.empty;
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
      info.textContent = box.dataset.failed;
    });
})();
