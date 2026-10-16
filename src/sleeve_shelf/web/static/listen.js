// An album's page: load what can be played of it, then play one preview or video at a time.
(function () {
  const section = document.getElementById("listen");
  if (!section) return;
  const audio = new Audio();
  let playing = null;

  function stop() {
    audio.pause();
    if (playing) playing.textContent = "\u25B6";
    playing = null;
  }
  audio.addEventListener("ended", stop);

  function wire() {
    section.querySelectorAll("[data-preview]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (playing === button) return stop();
        stop();
        audio.src = button.dataset.preview;
        audio.play().catch(stop);
        button.textContent = "\u275A\u275A";
        playing = button;
      });
    });
    // A video is only loaded from YouTube when asked for, without YouTube's cookies.
    section.querySelectorAll("[data-youtube]").forEach(function (button) {
      button.addEventListener("click", function () {
        stop();
        const frame = document.createElement("iframe");
        frame.className = "ss-video-frame";
        frame.src = "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(button.dataset.youtube) + "?autoplay=1";
        frame.allow = "autoplay; encrypted-media; picture-in-picture";
        frame.allowFullscreen = true;
        frame.title = button.getAttribute("aria-label");
        button.closest(".ss-video").after(frame);
        button.remove();
      });
    });
  }

  fetch(section.dataset.url)
    // 429: a visitor played many previews just now; the part says so.
    .then(function (response) { return response.ok || response.status === 429 ? response.text() : Promise.reject(); })
    .then(function (html) {
      const part = new DOMParser().parseFromString(html, "text/html").querySelector("[data-listen-body]");
      if (!part) return;
      section.querySelector("[data-listen-body]").replaceWith(part);
      wire();
    })
    .catch(function () {
      section.querySelector("[data-listen-body]").innerHTML =
        '<div class="ss-card-body ss-muted">' + section.dataset.offline + "</div>";
    });
})();
