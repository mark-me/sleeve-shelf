// Browse: the play button beside an album plays its previews from Deezer, one track after
// another, and shows which one plays under the album's title. One album plays at a time.
// Buttons are found by delegation, so rows that search-while-typing puts in place work too.
(function () {
  const audio = new Audio();
  const known = new Map(); // address -> tracks, so an album is fetched once per page
  let button = null;
  let queue = [];
  // The button pressed last: an album still being fetched when another is pressed is dropped.
  let wanted = null;

  function line(row) {
    let now = row.querySelector(".ss-now-playing");
    if (!now) {
      now = document.createElement("span");
      now.className = "ss-now-playing";
      (row.querySelector(".ss-row-text") || row).append(now);
    }
    return now;
  }

  function stop() {
    audio.pause();
    if (button) {
      button.textContent = "\u25B6";
      button.classList.remove("ss-playing");
      const now = button.closest(".ss-row").querySelector(".ss-now-playing");
      if (now) now.remove();
    }
    button = null;
    queue = [];
  }

  function next() {
    const track = queue.shift();
    if (!track || !button) return stop();
    line(button.closest(".ss-row")).textContent = "\u266A " + track.title;
    audio.src = track.preview;
    audio.play().catch(stop);
  }
  audio.addEventListener("ended", next);

  // Say why nothing plays, under the album's title.
  function say(target, text) {
    line(target.closest(".ss-row")).textContent = text;
  }

  document.addEventListener("click", async function (event) {
    const target = event.target.closest("[data-play-album]");
    if (!target) return;
    if (target === button) return stop();
    stop();
    if (wanted && wanted !== target) wanted.textContent = "\u25B6";
    wanted = target;
    const url = target.dataset.playAlbum;
    let tracks = known.get(url);
    if (!tracks) {
      target.textContent = "\u2026";
      let data = null;
      try {
        data = await (await fetch(url)).json();
      } catch (error) {
        // No answer at all: the app itself is out of reach.
      }
      target.textContent = "\u25B6";
      if (data && !data.unreachable) known.set(url, data.tracks);
      if (wanted !== target) return; // another album was pressed meanwhile
      if (!data || (data.unreachable && !data.tracks.length)) return say(target, window.browseText.offline);
      tracks = data.tracks;
    }
    if (!tracks.length) {
      // Deezer has none: the button says so, and the album's page may still have videos.
      target.disabled = true;
      target.textContent = "\u2013";
      return say(target, window.browseText.none);
    }
    button = target;
    button.textContent = "\u275A\u275A";
    button.classList.add("ss-playing");
    queue = tracks.slice();
    next();
  });
})();
