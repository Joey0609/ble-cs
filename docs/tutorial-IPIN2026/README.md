# IPIN 2026 Tutorial Slides

A [reveal.js](https://revealjs.com/) presentation with one HTML file per slide.
`index.html` fetches the files in `slides/` and joins them into the deck
before reveal.js starts.

## Viewing

The deck fetches its slide files, so it must be served over HTTP; opening
`index.html` from disk (`file://`) does not work. From this folder, run:

```sh
npm start
```

This starts `serve.js` (Node.js 18+, no dependencies to install) at
<http://localhost:8000/tutorial-IPIN2026/> and opens it in the default
browser. It serves the parent `docs/` folder, so the deck URL includes
`tutorial-IPIN2026/`. Use `npm start -- --port 8080` for another port, or
`npm start -- --no-open` to skip opening the browser. reveal.js is loaded from
the jsDelivr CDN, so the deck needs an internet connection.

Without Node.js, `python3 -m http.server 8000 -d docs` from the repository
root serves the same URL.

Useful keys: `S` opens the speaker view with notes, `O` or `Esc` shows the
slide overview, and `F` enters full screen.

## Adding a slide

1. Create `slides/NN-name.html` containing one `<section>…</section>`. Nest
   `<section>` elements inside it for vertical sub-slides.
2. Add the file name to the `SLIDES` array in `index.html` at the position
   where it should appear.

Speaker notes go in `<aside class="notes">…</aside>` inside a section. Math can
be written as `\( … \)` or `\[ … \]` (KaTeX). Scripts inside slide files do not
run; put shared behavior in `index.html`. Shared styles live in `theme.css`.
Put figures in `images/` so the deck is self-contained, and reference them as
`images/name.png`: image paths are relative to `index.html`, not to the slide
file.

## Step timing figures

`images/mode-{0..3}-timing.svg` are generated from the planner's step model
(`ble_channel_sounding_planner.model.step_segments`, default scenario), drawn to scale in the
style of the app's Individual step view. Regenerate them from the repository
root after changing the model or the script:

```sh
.venv/bin/python docs/tutorial-IPIN2026/make_timing_figures.py
```
