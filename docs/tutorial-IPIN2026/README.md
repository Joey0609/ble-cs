# IPIN 2026 Tutorial Slides

*SensWear · From Channel Sounding to Ring Tracks*: a [reveal.js](https://revealjs.com/)
deck with one HTML file per slide. `deck.js` fetches the files listed in
`slides.json` and joins them into the deck before reveal.js starts.

```text
index.html           page shell: reveal.js, KaTeX and fonts from CDNs
deck.js              loads slides.json and the slides, adds the header, starts reveal.js
slides.json          slide order, grouped into the sections of the header breadcrumb
slides/NN-<name>.html   one slide each, numbered in deck order; #/<name> links to it
                        (NN<a-z>-<name>.html: in a vertical stack below slide NN)
images/              figures, photos and app screenshots
theme.css            the deck theme
interactives.js      the RTT, PBR and frequency-offset demos
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
page serves this presentation at
<https://sens-wear.github.io/ble-cs/ipin2026-tutorial/>. Use
`npm start -- --port 8080` for another port, or `npm start -- --no-open` to
skip opening the browser. Without Node.js, `python3 -m http.server 8000 -d docs`
from the repository root serves the same local path.

The counter at the bottom right shows the current slide's number, e.g.
`14 / 32`.

Keys: `S` opens the speaker view with notes and a pacing timer, `O` or `Esc`
the overview, `F` full screen. On a slide with hidden answers, `↓` reveals the
next one and `↑` hides it; `←` and `→` change slide without revealing them. For a PDF, open `index.html?print-pdf` in
Chrome and print to PDF; add `&showNotes=true` to include the notes.

## Publish with GitHub Pages

The workflow in `.github/workflows/publish-tutorial.yml` publishes this folder
when changes are pushed to `main`, or when run manually from the Actions tab.
To enable it for the repository:

1. Open **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Push a change to `docs/tutorial-IPIN2026/` on `main`, or open **Actions →
   Publish tutorial presentation → Run workflow** and select `main`.
4. When the run succeeds, open
   <https://sens-wear.github.io/ble-cs/ipin2026-tutorial/>. The
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
   `"appendix": true` is left out of the main numbering; the breadcrumb shows
   it only from the last main section on.
3. Renumber the files after it (`git mv`) and their entries in `slides.json`,
   so file numbers keep matching the counter. The slide id and `#/<name>`
   link omit the number, so links and `theme.css` selectors are unaffected.

A slide can hold optional detail in a vertical stack below it, reached with the
down arrow (→ skips the stack; space walks through it). Name those files
`NN<a-z>-<name>.html` after their parent, in order, and give the parent an
entry with the slides below it:

```json
{ "slide": "14-bt-localization", "down": ["14a-find-me", "14b-beacons"] }
```

They count as `14a`, `14b` on the counter and do not change the main
numbering. Whenever another slide is available below, the same "Press ↓ to see
related slides" cue appears above the footer. Say what is below in the slide's
speaker notes.

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
style of the app's Individual step view. `images/acl-interval-layout.svg` places
one 72-channel procedure and its RAS transfer on the ACL timeline at 7.5, 15 and
30 ms, from the host application's planner (`ble_channel_sounding.planner.model`:
`build_schedule` with its RAS transfer model) and the step timings our nRF54 pair
selected. All use the deck's dark palette. Regenerate them from the repository
root after changing either model or the script:

```sh
.venv/bin/python docs/tutorial-IPIN2026/make_timing_figures.py
```

## CS setup and implementation stacks

Main slides 23–26 use the same vertical detail navigation as the preceding
technical slides:

- **23 — CS procedure initialization:** negotiated parameters, conditional FAE
  retrieval (`No_FAE = 0` and no known table), then procedure start.
- **24 — Two-way measurements must meet in one place:** each end keeps half of
  every observable; RAS returns the reflector's half as a GATT service on the
  ACL link, scheduled with CS; for PBR, Inline PCT Transfer lets the initiator
  measure the two-way phase itself. Below it, RAS delivery, the IPT phase
  relation and capability/timing/data tradeoffs. IPT is explicitly labeled
  Core 6.3; the mode and security slides use the Core 6.0 baseline.
- **25 — Why ranging needs security:** distance as an access decision, relay
  and distance-reduction attacks; below it, one slide on how CS answers each
  attack, with a single line on the CS security levels. The level details stay
  in the speaker notes.
- **26 — Practical implementation: four decisions.** Mode-0 steps, subevents,
  spacing and the controllers' step timings form one time budget, paid in radio
  time and energy; the ATT MTU sets how long RAS holds the link; the ACL
  interval sets what fits in the schedule and how a procedure is split; the CS
  security level follows the use case. Below it, built from the step up: step
  timings, the mode-0/subevent/spacing budget, measurement cost, RAS airtime,
  the interval layout figure, choosing the interval, and security by use case. Numbers come from the host planner with our nRF54
  pair's step timings and from lab runs in `implementation_plan.md`.

Press ↓ for details or → to continue to the next main topic. The remaining
main slides continue at 27; slide IDs and hash links survive renumbering.
