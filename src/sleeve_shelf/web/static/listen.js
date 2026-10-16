// An album's page: load what can be played of it, then play one thing at a time — a preview,
// or a video. Starting one stops what plays: a preview is paused, a video taken away again.
(function () {
  const section = document.getElementById("listen");
  if (!section) return;
  const audio = new Audio();
  let preview = null; // the button of the preview playing
  let video = null; // {frame, button} of the video showing

  function stop() {
    audio.pause();
    if (preview) preview.textContent = "\u25B6";
    preview = null;
    if (video) {
      // Taking the frame away is the only way to stop a YouTube video from here.
      video.frame.replaceWith(video.button);
      video = null;
    }
  }
  audio.addEventListener("ended", stop);

  function wire() {
    section.querySelectorAll("[data-preview]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (preview === button) return stop();
        stop();
        audio.src = button.dataset.preview;
        audio.play().catch(stop);
        button.textContent = "\u275A\u275A";
        preview = button;
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
        button.replaceWith(frame);
        video = { frame: frame, button: button };
      });
    });
  }

  // What is shown when nothing could be loaded: plain text, never markup.
  function notice(text) {
    const body = document.createElement("div");
    body.className = "ss-card-body ss-muted";
    body.textContent = text;
    const card = section.querySelector("[data-listen-body]");
    card.replaceChildren(body);
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
      notice(section.dataset.offline);
    });
})();
