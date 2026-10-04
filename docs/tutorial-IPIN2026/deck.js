// Builds the deck from slides.json: fetches slides/<file>.html in order, adds
// the shared header, then starts reveal.js. Files are named <NN>-<name> (R<NN>-
// in the appendix, <NN><a-z>- below a slide); each slide's id is <name>, so
// #/<name> links to it and survives renumbering.

const deck = document.querySelector('.reveal .slides');
const counter = document.getElementById('deck-counter');
const downMarker = document.querySelector('.deck-down-hint');

function showChineseHelp() {
  let dialog = document.querySelector('.shortcut-dialog');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.className = 'terminology-dialog shortcut-dialog';
    dialog.innerHTML = '<button class="terminology-close" type="button">关闭</button><h2>演示快捷键</h2><p>← / →：上一页／下一页主讲内容</p><p>↓ / ↑：查看下钻讲解，或显示／隐藏答案</p><p>空格：顺序浏览内容</p><p>S：讲者视图与备注</p><p>O 或 Esc：页面总览</p><p>F：全屏</p><p>F1 或 ?：本说明</p><p>点击应用截图可放大；点击放大图或按 Esc 关闭。</p><p>页脚“缩写全称与中文”可查看英文全称和中文解释。</p>';
    dialog.querySelector('button').onclick = () => dialog.close();
    document.body.append(dialog);
  }
  if (!dialog.open) dialog.showModal();
}

const slideId = (file) => file.replace(/^R?\d+[a-z]?-/, '');

// A slides.json entry is a file, or {"slide": file, "down": [files]} for a
// slide with a vertical stack below it, reached with the down arrow.
const top = (entry) => entry.slide ?? entry;
const below = (entry) => entry.down ?? [];

// Header breadcrumb: a window of five sections with the current one in the
// middle, taken from the main sections plus, on the last main section and the
// appendix slides, the appendix sections after it.
// Near either end the window stays full and the current section moves off
// centre. An ellipsis marks the sections left out on either side.
const CRUMBS = 5;
function header(label, sections, current) {
  const lastMain = sections.filter((section) => !section.appendix).at(-1);
  const tail = current === lastMain || current.appendix;
  const all = sections.filter((section) => !section.appendix || tail);
  const at = all.indexOf(current);
  const centred = at - Math.floor((CRUMBS - 1) / 2);
  const start = Math.max(0, Math.min(centred, all.length - CRUMBS));
  const items = all.slice(start, start + CRUMBS).map((section, i) => {
    const state = start + i === at ? 'current' : start + i < at ? 'complete' : 'upcoming';
    const aria = start + i === at ? ' aria-current="step"' : '';
    return `<li class="${state}"><a href="#/${slideId(top(section.slides[0]))}"${aria}>${section.title}</a></li>`;
  });
  const more = '<li class="more" aria-hidden="true">…</li>';
  if (start > 0) items.unshift(more);
  if (start + CRUMBS < all.length) items.push(more);
  const div = document.createElement('div');
  div.className = 'eyebrow';
  div.innerHTML = `<span>${label}</span>`
    + `<nav class="breadcrumb" aria-label="教程进度"><ol>${items.join('')}</ol></nav>`;
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

// Counter text per file: main slides count as 01 / 38, and the slides below
// one as 12a, 12b, …; appendix slides count within their section.
function counterLabels(sections) {
  const labels = new Map();
  const main = sections.filter((s) => !s.appendix).flatMap((s) => s.slides);
  for (const section of sections) {
    section.slides.forEach((entry, i) => {
      const n = section.appendix
        ? `${section.title} ${i + 1}`
        : String(main.indexOf(entry) + 1).padStart(2, '0');
      const total = section.appendix ? section.slides.length : main.length;
      labels.set(top(entry), `${n} / ${total}`);
      below(entry).forEach((file, j) => {
        labels.set(file, `${n}${String.fromCharCode(97 + j)} / ${total}`);
      });
    });
  }
  return labels;
}

// Shows the slide's number, with a separate cue above the footer
// whenever another slide is available below.
function updateFooter(labels) {
  const slide = Reveal.getCurrentSlide();
  const { file } = slide.dataset;
  const hasBelow = slide.parentElement !== deck
    && slide.nextElementSibling?.matches('section');
  counter.textContent = labels.get(file);
  downMarker.hidden = !hasBelow;
}

try {
  const response = await fetch('slides.json');
  if (!response.ok) {
    throw new Error(`slides.json: HTTP ${response.status}`);
  }
  const { header: label, sections } = await response.json();
  for (const section of sections) {
    const entries = await Promise.all(
      section.slides.map((entry) => Promise.all([top(entry), ...below(entry)].map(load))),
    );
    entries.forEach((slides, i) => {
      const entry = section.slides[i];
      [top(entry), ...below(entry)].forEach((file, j) => {
        slides[j].id = slideId(file);
        slides[j].dataset.file = file;
        slides[j].prepend(header(label, sections, section));
      });
      if (slides.length === 1) {
        deck.append(slides[0]);
      } else {
        // reveal.js shows a <section> of <section>s as a vertical stack.
        const stack = document.createElement('section');
        stack.append(...slides);
        deck.append(stack);
      }
    });
  }

  // The demos look up their controls by id, so they load after the slides.
  const { translateScreenshots } = await import('./screenshot-translations.js');
  await translateScreenshots(deck);
  const { explainAbbreviations } = await import('./terminology.js');
  explainAbbreviations(deck);
  await import('./interactives.js');
  // Keep arrow keys and space inside the demo controls.
  deck.querySelectorAll('input, button, select').forEach((control) => {
    control.addEventListener('keydown', (event) => {
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown', ' '].includes(event.key)) {
        event.stopPropagation();
      }
    });
  });

  const labels = counterLabels(sections);
  Reveal.on('ready', () => updateFooter(labels));
  Reveal.on('slidechanged', () => updateFooter(labels));
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
    // ← and → always change slide, so ↓ and ↑ alone reveal and hide
    // fragments such as quiz answers. Shift jumps to the first or last slide.
    keyboard: {
      112: showChineseHelp,
      191: showChineseHelp,
      37: (event) => (event.shiftKey ? Reveal.slide(0) : Reveal.left({ skipFragments: true })),
      39: (event) => (event.shiftKey
        ? Reveal.slide(Reveal.getHorizontalSlides().length - 1)
        : Reveal.right({ skipFragments: true })),
    },
    plugins: [RevealNotes, RevealMath.KaTeX],
    katex: { version: '0.16.22' },
  });
} catch (error) {
  deck.innerHTML = `
    <section>
      <h2>演示稿加载失败</h2>
      <div class="content">
        <p>${error.message}</p>
        <p>请通过 HTTP 服务器打开本目录；<code>file://</code> 页面无法加载
        幻灯片文件。请参阅 README.md。</p>
      </div>
    </section>`;
  Reveal.initialize({ width: 1280, height: 720, center: false });
}
