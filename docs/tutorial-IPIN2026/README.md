# IPIN 2026 Tutorial Slides

*SensWear · From Channel Sounding to Ring Tracks*: a [reveal.js](https://revealjs.com/)
deck with one HTML file per slide. `deck.js` fetches the files listed in
`slides.json` and joins them into the deck before reveal.js starts.

```text
index.html           page shell: reveal.js, KaTeX and fonts from CDNs
deck.js              loads slides.json and the slides, adds the header, starts reveal.js
slides.json          slide order, grouped into the sections of the header breadcrumb
slides/NN-<name>.html   one slide each, numbered in deck order; #/<name> links to it
images/              figures, photos and app screenshots
theme.css            the deck theme
interactives.js      the RTT, PBR and geometry demos
sources.html         sources, screenshot provenance and asset credits
serve.js             local preview server (npm start)
make_timing_figures.py   draws images/*-timing.svg from the planner model
```

## Viewing

The deck needs no build step and no installed packages. reveal.js 5.2.1,
KaTeX 0.16.22 and the Outfit and Space Mono fonts load from jsDelivr and Google
Fonts, so it needs an internet connection. It is published as a static site on
GitHub Pages. Locally, serve it over HTTP; a `file://` page cannot fetch the
slide files. From this folder, run:

```sh
npm start
```

This starts `serve.js` (Node.js 18+, nothing to install) at
<http://localhost:8023/tutorial-IPIN2026/> and opens it in the default browser.
It serves the parent `docs/` folder for local previews. The published project
page serves this presentation at <https://sens-wear.github.io/ble-cs/>. Use
`npm start -- --port 8080` for another port, or `npm start -- --no-open` to
skip opening the browser. Without Node.js, `python3 -m http.server 8000 -d docs`
from the repository root serves the same local path.

Keys: `S` opens the speaker view with notes and a pacing timer, `O` or `Esc`
the overview, `F` full screen. For a PDF, open `index.html?print-pdf` in
Chrome and print to PDF; add `&showNotes=true` to include the notes.

## Publish with GitHub Pages

The workflow in `.github/workflows/publish-tutorial.yml` publishes this folder
when changes are pushed to `main`, or when run manually from the Actions tab.
To enable it for the repository:

1. Open **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Push a change to `docs/tutorial-IPIN2026/` on `main`, or open **Actions →
   Publish tutorial presentation → Run workflow** and select `main`.
4. When the run succeeds, open <https://sens-wear.github.io/ble-cs/>. The
   deployment URL is also shown in the workflow run's `github-pages` environment.

## Adding a slide

1. Create `slides/NN-<name>.html` holding one `<section>`. `NN` is the slide's
   number on the deck counter; appendix slides use `R<NN>-`, numbered within
   the appendix:

   ```html
   <section data-timing="90">
     <h2>Slide title</h2>
     <div class="content">…</div>
     <div class="source"><a href="…">Credit</a></div>
     <aside class="notes"><p>Speaker notes.</p></aside>
   </section>
   ```

2. Add `NN-<name>` to its section in `slides.json`. A section with
   `"appendix": true` is left out of the main breadcrumb and numbering.
3. Renumber the files after it (`git mv`) and their entries in `slides.json`,
   so file numbers keep matching the counter. The slide id and `#/<name>`
   link omit the number, so links and `theme.css` selectors are unaffected.

`deck.js` adds the header and breadcrumb; do not repeat them in the slide.
`data-timing` is the planned time in seconds for the speaker view. The content
block is either `<div class="content">`, sized in pixels (cards, `cols`,
`callout`, `formula`, photos), or `<div class="body">`, sized in em from 32px as
the technical diagrams are; `theme.css` lists the classes for each. If a
`body` slide is too tall, shrink it with `style="zoom: 0.9"` on the `body`
element.

Math is written as `\( … \)` or `\[ … \]` (KaTeX). Scripts inside slide files
do not run; put demo code in `interactives.js`. Image paths are relative to
`index.html`: `images/name.png`.

## Step timing figures

`images/mode-{0..3}-timing.svg` are generated from the planner's step model
(`ble_channel_sounding_planner.model.step_segments`, default scenario), drawn to scale in the
style of the app's Individual step view. `images/acl-cs-timing.svg` places the
steps from the planner's `build_schedule` on the ACL connection timeline, using
the firmware's default connection and procedure parameters. Both use the deck's
dark palette. Regenerate them from the repository root after changing the model
or the script:

```sh
.venv/bin/python docs/tutorial-IPIN2026/make_timing_figures.py
```
