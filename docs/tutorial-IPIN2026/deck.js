// Builds the deck from slides.json: fetches slides/<file>.html in order, adds
// the shared header, then starts reveal.js. Files are named <NN>-<name> (R<NN>-
// in the appendix); each slide's id is <name>, so #/<name> links to it and
// survives renumbering.

const deck = document.querySelector('.reveal .slides');
const counter = document.getElementById('deck-counter');

const slideId = (file) => file.replace(/^R?\d+-/, '');

// Header breadcrumb: the main sections, plus the current one on appendix slides.
function header(label, sections, current) {
  const shown = sections.filter((section) => !section.appendix || section === current);
  const at = shown.indexOf(current);
  const items = shown.map((section, i) => {
    const state = i === at ? 'current' : i < at ? 'complete' : 'upcoming';
    const aria = i === at ? ' aria-current="step"' : '';
    return `<li class="${state}"><a href="#/${slideId(section.slides[0])}"${aria}>${section.title}</a></li>`;
  });
  const div = document.createElement('div');
  div.className = 'eyebrow';
  div.innerHTML = `<span>${label}</span>`
    + `<nav class="breadcrumb" aria-label="Tutorial progress"><ol>${items.join('')}</ol></nav>`;
  return div;
}

async function load(name) {
  const response = await fetch(`slides/${name}.html`);
  if (!response.ok) {
    throw new Error(`slides/${name}.html: HTTP ${response.status}`);
  }
  const template = document.createElement('template');
  template.innerHTML = await response.text();
  const section = template.content.firstElementChild;
  if (section?.localName !== 'section') {
    throw new Error(`slides/${name}.html must hold one <section>`);
  }
  return section;
}

// Main slides count as 01 / 54; appendix slides count within their section.
function updateCounter(sections) {
  const slide = Reveal.getCurrentSlide();
  const section = sections.find((s) => s.slides.map(slideId).includes(slide.id));
  if (section.appendix) {
    counter.textContent = `${section.title} ${section.slides.map(slideId).indexOf(slide.id) + 1} / ${section.slides.length}`;
  } else {
    const main = sections.filter((s) => !s.appendix).flatMap((s) => s.slides.map(slideId));
    counter.textContent = `${String(main.indexOf(slide.id) + 1).padStart(2, '0')} / ${main.length}`;
  }
}

try {
  const response = await fetch('slides.json');
  if (!response.ok) {
    throw new Error(`slides.json: HTTP ${response.status}`);
  }
  const { header: label, sections } = await response.json();
  for (const section of sections) {
    const slides = await Promise.all(section.slides.map(load));
    slides.forEach((slide, i) => {
      slide.id = slideId(section.slides[i]);
      slide.prepend(header(label, sections, section));
      deck.append(slide);
    });
  }

  // The demos look up their controls by id, so they load after the slides.
  await import('./interactives.js');
  // Keep arrow keys and space inside the demo controls.
  deck.querySelectorAll('input, button, select').forEach((control) => {
    control.addEventListener('keydown', (event) => {
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown', ' '].includes(event.key)) {
        event.stopPropagation();
      }
    });
  });

  Reveal.on('ready', () => updateCounter(sections));
  Reveal.on('slidechanged', () => updateCounter(sections));
  Reveal.initialize({
    width: 1280,
    height: 720,
    margin: 0.04,
    center: false,
    hash: true,
    transition: 'none',
    backgroundTransition: 'none',
    // Pacing for the speaker view (S); slides override it with data-timing.
    defaultTiming: 60,
    plugins: [RevealNotes, RevealMath.KaTeX],
    katex: { version: '0.16.22' },
  });
} catch (error) {
  deck.innerHTML = `
    <section>
      <h2>Could not load the slides</h2>
      <div class="content">
        <p>${error.message}</p>
        <p>Serve this folder over HTTP; <code>file://</code> pages cannot fetch
        the slide files. See README.md.</p>
      </div>
    </section>`;
  Reveal.initialize({ width: 1280, height: 720, center: false });
}
