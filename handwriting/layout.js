// Runs after fonts load, before final delimiter replacement and PDF printing.
const layoutRandom = mkRand(layoutConfig.seed + 104729);
const layoutReport = {pages: [], equations: [], lines: [], warnings: []};
function mathWidth(el) {
  const ink = el.querySelector('.katex-html');
  return ink ? Math.max(ink.getBoundingClientRect().width, ink.scrollWidth) : el.scrollWidth;
}
function prepareEquations() {
  document.querySelectorAll('.display-math-src').forEach(el => {
    const parts = JSON.parse(el.dataset.parts || '[]');
    const available = el.clientWidth - 32;
    const original = el.dataset.tex;
    function render(tex) {
      el.dataset.tex = tex;
      katex.render(tex, el, {displayMode: true, throwOnError: false});
      decorateMath(el);
    }
    const lines = [];
    let current = '';
    for (const part of parts) {
      render(current + part);
      const matrices = ((current + part).match(/\\begin\{(?:[bpBvV]?matrix|array)\}/g) || []).length;
      if (current && (mathWidth(el) > available || (matrices > 2 && /\\(?:xrightarrow|rightarrow|to)(?![a-z])/.test(current + part)))) {
        lines.push(current);
        current = part;
      } else current += part;
    }
    lines.push(current || original);
    for (const tex of lines) {
      const line = document.createElement('div');
      line.className = 'display-math-src';
      line.dataset.tex = tex;
      katex.render(tex, line, {displayMode: true, throwOnError: false});
      el.before(line);
      decorateMath(line);
    }
    el.remove();
    layoutReport.equations.push({latex: original, appliedLines: lines.length});
  });
}
// Keep the ruled grid: pad each display-math block out to a whole number of
// ruled lines, so the prose after it lands back on a line.
function padDisplayMathToRules() {
  const LH = layoutConfig.lineHeight;
  document.querySelectorAll('.display-math-src').forEach(el => {
    // The border box already includes the block's vertical padding, which is
    // what separates display math from its neighbours. Padding is used rather
    // than margin precisely so this arithmetic holds: adjacent vertical margins
    // collapse to the larger of the two instead of adding, so a block padded
    // with margins advances the flow by less than its measured height, and
    // consecutive equations walk the text off the rules.
    const st = getComputedStyle(el);
    const total = el.getBoundingClientRect().height;
    const target = Math.ceil(total / LH - 0.01) * LH;
    el.style.paddingBottom = ((parseFloat(st.paddingBottom) || 0) + (target - total)) + 'px';
  });
}
function paginate() {
  const LH = layoutConfig.lineHeight;
  const source = document.getElementById('source');
  // Build actual lines from measured atomic words/math. Bound word count as well
  // as width so strings of short words cannot pack the whole writable column.
  source.querySelectorAll('.para').forEach((para, paragraphId) => {
    const atoms = [];
    function collect(node, label = false) {
      if (node.nodeType === Node.TEXT_NODE) {
        if (node.textContent.trim()) {
          for (const word of node.textContent.trim().split(/\s+/)) {
            const span = document.createElement('span');
            span.className = 'w'; span.textContent = word;
            if (label) span.classList.add('label');
            atoms.push(span);
          }
        }
      } else if (node.matches('.w, .math-src')) {
        if (label) node.classList.add('label');
        atoms.push(node);
      } else Array.from(node.childNodes).forEach(child => collect(child, label || node.matches('.label')));
    }
    Array.from(para.childNodes).forEach(node => collect(node));
    const isHeading = !!para.querySelector('.label');
    para.replaceChildren();
    let line, words;
    function newLine() {
      line = document.createElement('div'); line.className = 'hand-line';
      const indent = layoutConfig.jitter ? layoutRandom() * 8 : 0;
      line.style.marginLeft = indent + 'px';
      line.style.wordSpacing = '0px';
      line.dataset.gap = (layoutConfig.jitter ? .22 + layoutRandom() * .16 : .3);
      para.append(line); words = 0;
    }
    newLine();
    for (const atom of atoms) {
      const count = atom.matches('.math-src') ? 0 : 1;
      const gap = document.createElement('span');
      gap.textContent = ' '; gap.style.display = 'inline-block';
      gap.style.width = line.dataset.gap + 'em';
      if (line.childNodes.length) line.append(gap);
      line.append(atom);
      const width = atom.getBoundingClientRect().right - line.getBoundingClientRect().left;
      if (line.childNodes.length > 1 && (width > line.clientWidth - 8 || words + count > 11)) {
        atom.remove(); gap.remove(); newLine(); line.append(atom);
      }
      words += count;
      line.dataset.words = words;
    }
    if (isHeading) para.firstElementChild.dataset.heading = 'true';
    Array.from(para.children).forEach((line, index) => {
      line.dataset.paragraph = paragraphId;
      line.dataset.paragraphStart = index === 0 ? 'true' : 'false';
    });
    // Paragraphs become splittable at real line boundaries.
    para.replaceWith(...para.children);
  });
  let page, used, capacity, section;
  function newPage(minHeight = 0) {
    page = document.createElement('div'); page.className = 'page';
    const bottom = parseFloat(getComputedStyle(source).paddingBottom);
    const choices = [2, 3, 4].filter(n => layoutConfig.pageHeight - layoutConfig.baseTop - n * LH - bottom >= minHeight);
    const allowed = choices.length ? choices : [2, 3, 4];
    const blank = allowed[Math.floor(layoutRandom() * allowed.length)];
    const top = layoutConfig.baseTop + blank * LH;
    page.style.paddingTop = top + 'px';
    document.body.append(page);
    capacity = layoutConfig.pageHeight - top - parseFloat(getComputedStyle(page).paddingBottom);
    if (capacity < LH * 4) throw new Error('Paper/font settings leave fewer than four writable lines');
    used = 0; section = null;
    layoutReport.pages.push({page: layoutReport.pages.length + 1, blankTopLines: blank, problems: [], usedHeight: 0, capacity});
  }
  function height(el) {
    const s = getComputedStyle(el);
    return el.getBoundingClientRect().height
      + (parseFloat(s.marginTop) || 0) + (parseFloat(s.marginBottom) || 0);
  }
  for (const group of Array.from(source.children)) {
    const units = Array.from(group.children);
    const total = units.reduce((n, el) => n + height(el), 0);
    if (!page) newPage(total);
    const firstChunk = units.slice(0, 2).reduce((n, el) => n + height(el), 0);
    // Keep a short solution whole. Long solutions continue at line or equation
    // boundaries; never put a fresh question in the last four ruled lines.
    const maxFreshCapacity = layoutConfig.pageHeight - layoutConfig.baseTop - 2 * LH - parseFloat(getComputedStyle(page).paddingBottom);
    if (used && (capacity - used < Math.max(4 * LH, firstChunk) ||
        (total <= maxFreshCapacity && total > capacity - used))) newPage(total);
    section = null;
    for (let i = 0; i < units.length; i++) {
      const el = units[i];
      const h = height(el);
      const next = units[i + 1];
      const keepNext = next && el.classList.contains('hand-line') && next.classList.contains('display-math-src');
      let required = h + (keepNext ? height(next) : 0);
      if (el.dataset.paragraph !== undefined) {
        const rest = [];
        for (let j = i; j < units.length && units[j].dataset.paragraph === el.dataset.paragraph; j++) rest.push(units[j]);
        const paragraphHeight = rest.reduce((n, unit) => n + height(unit), 0);
        // Keep short paragraphs whole; longer ones keep at least two lines
        // together at each break so a last clause never gets its own page.
        if (el.dataset.paragraphStart === 'true' && paragraphHeight <= 6 * LH) required = Math.max(required, paragraphHeight);
        else if (rest.length === 2 || el.dataset.paragraphStart === 'true') required = Math.max(required, h + (rest[1] ? height(rest[1]) : 0));
      }
      if (used && used + required > capacity) {
        newPage(); section = null;
      }
      if (!section) {
        section = document.createElement('div'); section.className = 'problem-block';
        section.dataset.problem = group.dataset.problem; page.append(section);
        layoutReport.pages.at(-1).problems.push(group.dataset.problem);
      }
      section.append(el); used += h;
      if (h > capacity) layoutReport.warnings.push('Problem ' + group.dataset.problem + ': indivisible block exceeds page height; split this expression manually.');
      layoutReport.pages.at(-1).usedHeight = used;
    }
  }
  source.remove();
  document.querySelectorAll('.page .hand-line').forEach(line => {
    const words = Number(line.dataset.words);
    const p = line.closest('.page');
    const pageNumber = Array.from(document.querySelectorAll('.page')).indexOf(p) + 1;
    layoutReport.lines.push({page: pageNumber, words, heading: line.dataset.heading === 'true', top: line.getBoundingClientRect().top - p.getBoundingClientRect().top});
    if (layoutConfig.jitter) line.style.transform = `translateY(${(layoutRandom() - .5) * 3}px) rotate(${(layoutRandom() - .5) * .7}deg)`;
  });
  document.querySelectorAll('.page .math-src, .page .display-math-src').forEach(el => {
    const available = el.classList.contains('math-src') ? el.closest('.hand-line').clientWidth - 8 : el.clientWidth - 8;
    const width = mathWidth(el);
    if (width > available + 1) layoutReport.warnings.push(`Overwide equation (${Math.round(width)}px / ${Math.round(available)}px): ${el.dataset.tex}. Split its prose or expression manually.`);
  });
  document.querySelectorAll('.katex-error').forEach(el => layoutReport.warnings.push('Invalid LaTeX: ' + el.textContent));
  layoutReport.pageCount = layoutReport.pages.length;
  layoutReport.averageWordsPerLine = layoutReport.lines.length ? +(layoutReport.lines.reduce((n, l) => n + l.words, 0) / layoutReport.lines.length).toFixed(1) : 0;
  window.__layoutReport = layoutReport;
}
