// Character choice is deterministic per expression, including measurement passes.
const fontData = handwritingConfig.resources;
const coverage = Object.fromEntries(Object.entries(fontData).map(([name, data]) => [name, new Set(Array.from(data.coverage))]));
const svgNS = 'http://www.w3.org/2000/svg';
function textSeed(text) {
  let value = handwritingConfig.seed >>> 0;
  for (const ch of text) value = Math.imul(value ^ ch.codePointAt(0), 16777619) >>> 0;
  return value;
}
function normalizedGlyph(ch) {
  if (ch === 'µ') return 'μ';
  const n = ch.codePointAt(0);
  if (n >= 0x1d400 && n <= 0x1d7ff) return ch.normalize('NFKC');
  return ch;
}
function coveredFamilies(ch) { return Object.keys(coverage).filter(name => coverage[name].has(ch)); }
function chooseGlyph(ch, random) {
  const choices = coveredFamilies(ch);
  return choices.length ? choices[Math.floor(random() * choices.length)] : null;
}
function decorateLetters(root, random, math) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let node;
  while ((node = walker.nextNode())) {
    const parent = node.parentElement;
    if (!node.textContent.trim() || !parent || parent.closest('.hand-glyph, .katex-mathml, svg')) continue;
    if (math && parent.closest('.delimsizing, .op-symbol, .stretchy, .sqrt-sign, .accent-body, .svg-align, .nulldelimiter')) continue;
    nodes.push(node);
  }
  for (const text of nodes) {
    const fragment = document.createDocumentFragment();
    for (const original of Array.from(text.textContent)) {
      if (/\s|\u200b/.test(original)) { fragment.append(document.createTextNode(original)); continue; }
      const styled = math && text.parentElement.closest('.mathbb, .mathfrak, .mathscr, .mathcal');
      const ch = styled ? original : normalizedGlyph(original);
      const family = styled ? null : chooseGlyph(ch, random);
      const span = document.createElement('span');
      span.className = 'hand-glyph';
      span.dataset.original = original;
      span.dataset.character = ch;
      span.dataset.codepoint = 'U+' + original.codePointAt(0).toString(16).toUpperCase().padStart(4, '0');
      span.textContent = ch;
      if (family) {
        span.dataset.font = family;
        span.style.setProperty('font-family', family, 'important');
        span.style.setProperty('font-style', 'normal', 'important');
      } else {
        span.dataset.fallback = styled ? 'mathematical alphabet preserves its distinct meaning' : 'no supplied font contains this character';
        if (!styled) span.style.setProperty('font-family', math ? 'KaTeX_Main' : 'serif', 'important');
      }
      fragment.append(span);
    }
    text.replaceWith(fragment);
  }
}
function decorateProse() {
  document.querySelectorAll('#source .w').forEach((word, i) => decorateLetters(word, mkRand(textSeed(word.textContent + i)), false));
}
function median(values) {
  const ordered = values.slice().sort((a,b) => a-b);
  return ordered.length ? (ordered[Math.floor((ordered.length-1)/2)] + ordered[Math.floor(ordered.length/2)]) / 2 : null;
}
function referenceStroke(root) {
  const fontSize = parseFloat(getComputedStyle(root.querySelector('.katex') || root).fontSize);
  // Keep one calibrated pen weight across row counts; random glyph choice must
  // not make an otherwise identical matrix change its bracket thickness.
  const values = Object.values(fontData).map(data => data.profile?.referenceStrokeEm).filter(Boolean);
  return median(values) * fontSize;
}
function makeSvg(width, height, className) {
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('width', width); svg.setAttribute('height', height);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('aria-hidden', 'true'); svg.classList.add(className);
  svg.style.cssText = 'position:absolute;overflow:visible;pointer-events:none;';
  svg.style.setProperty('width', width + 'px', 'important');
  svg.style.setProperty('height', height + 'px', 'important');
  return svg;
}
function addStroke(svg, points, width) {
  const path = document.createElementNS(svgNS, 'path');
  path.setAttribute('d', points.map((p,i) => `${i ? 'L' : 'M'}${p[0].toFixed(3)},${p[1].toFixed(3)}`).join(' '));
  path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'currentColor');
  path.style.setProperty('fill', 'none', 'important');
  path.style.setProperty('stroke', 'currentColor', 'important');
  path.setAttribute('stroke-width', width); path.setAttribute('stroke-linecap', 'round');
  path.setAttribute('stroke-linejoin', 'round'); path.setAttribute('vector-effect', 'non-scaling-stroke');
  svg.append(path);
}
function unionRect(el) {
  const boxes = [el, ...el.querySelectorAll('*')].map(n => n.getBoundingClientRect()).filter(r => r.width && r.height);
  return {left: Math.min(...boxes.map(r => r.left)), right: Math.max(...boxes.map(r => r.right)), top: Math.min(...boxes.map(r => r.top)), bottom: Math.max(...boxes.map(r => r.bottom))};
}
function annotateIssue(el, reason) { el.dataset.handwritingIssue = reason; }
function decorateVectors(root, random) {
  const semanticAccents = Array.from(root.querySelectorAll('.katex-mathml mover'));
  for (const [accentIndex, accent] of Array.from(root.querySelectorAll('.katex-accent')).entries()) {
    if (accent.querySelector('.hand-vector-arrow')) continue;
    const vlist = accent.querySelector('.vlist');
    const baseRow = vlist?.children[0];
    const markRow = vlist?.children[1];
    const base = baseRow && Array.from(baseRow.children).find(n => !n.classList.contains('pstrut'));
    const mark = markRow && (markRow.querySelector('.accent-body') || markRow.querySelector('.hide-tail'));
    if (!base || !mark) continue;
    // KaTeX's vector arrow has a path named vec; overrightarrow uses a long arrow.
    const vector = ['→', '⃗'].includes(semanticAccents[accentIndex]?.lastElementChild?.textContent.trim());
    if (!vector) { annotateIssue(mark, 'structural accent retains KaTeX drawing'); continue; }
    const families = Object.keys(fontData).filter(name => fontData[name].profile?.arrow && coverage[name].has('→'));
    if (!families.length) { annotateIssue(mark, 'handwritten arrow geometry unavailable'); continue; }
    const family = families[Math.floor(random() * families.length)];
    const shape = fontData[family].profile.arrow;
    const br = unionRect(base), ar = accent.getBoundingClientRect();
    const fs = parseFloat(getComputedStyle(root.querySelector('.katex')).fontSize);
    const stroke = referenceStroke(root);
    const headScale = fs * .16 / Math.max(shape.height, 1);
    const width = Math.max(br.right - br.left, fs * .55);
    const height = Math.max(shape.height * headScale, stroke * 2);
    const pointsAll = [shape.shaft, ...shape.head];
    const headStart = Math.min(...shape.head.flat().map(p => p[0]));
    const headWidth = (shape.width - headStart) * headScale;
    const transform = p => [p[0] >= headStart ? width - (shape.width-p[0])*headScale : p[0] / Math.max(headStart,1) * (width-headWidth), p[1]*headScale];
    const svg = makeSvg(width, height, 'hand-vector-arrow');
    svg.dataset.sampleFamily = family;
    svg.setAttribute('stroke-width', stroke);
    for (const points of pointsAll) addStroke(svg, points.map(transform), stroke);
    // Ink sits below the glyph's em-box top; use glyph-specific canvas ink bounds.
    const inkTops = Array.from(base.querySelectorAll('.hand-glyph[data-font]')).map(g => {
      const ctx = document.createElement('canvas').getContext('2d');
      const style = getComputedStyle(g);
      ctx.font = `${style.fontSize} '${g.dataset.font}'`;
      const metrics = ctx.measureText(g.textContent);
      const probe = document.createElement('span');
      probe.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline';
      g.append(probe); const baseline = probe.getBoundingClientRect().top; probe.remove();
      return baseline - metrics.actualBoundingBoxAscent;
    });
    const inkTop = inkTops.length ? Math.min(...inkTops) : br.top;
    const top = inkTop - height - Math.max(2, fs * .05);
    svg.style.left = `${(br.left+br.right-width)/2-ar.left}px`;
    svg.style.top = `${top-ar.top}px`;
    accent.style.position = 'relative';
    mark.style.visibility = 'hidden';
    accent.append(svg);
    // Reserve any extra vertical extent without moving the baseline.
    const extra = Math.max(0, ar.top-top);
    if (extra) accent.style.paddingTop = extra + 'px';
  }
}
function decorateBrackets(root, random) {
  if (!handwritingConfig.handDelims) return;
  const wanted = delimsFromTex(root.dataset.tex || '');
  let index = 0;
  const choices = Object.keys(fontData).filter(name => fontData[name].profile?.brackets);
  const reference = referenceStroke(root);
  // Matched pairs share pen weight; their handwritten shapes may vary by seed.
  const stack = [];
  for (const parent of root.querySelectorAll('.mopen, .mclose')) {
    if (parent.querySelector('.hand-bracket')) continue;
    const el = parent.querySelector('.delimsizing') || parent;
    let ch = el.textContent.replace(/[\s\u200b]/g, '');
    const stretchy = el !== parent || parent.classList.contains('delimcenter');
    if (stretchy) {
      if (!ch) ch = wanted[index] || '';
      if (wanted[index] === ch) index++;
    }
    if (ch !== '[' && ch !== ']') continue;
    if (!choices.length || !reference) { annotateIssue(el, 'square bracket sample geometry unavailable'); continue; }
    const family = ch === '[' ? choices[Math.floor(random()*choices.length)] : (stack.pop() || choices[Math.floor(random()*choices.length)]);
    if (ch === '[') stack.push(family);
    const shape = fontData[family].profile.brackets[ch];
    if (!shape) { annotateIssue(el, 'square bracket sample geometry unavailable'); continue; }
    const own = el.getBoundingClientRect();
    let bounds = el.children.length ? unionRect(el) : null;
    if (!bounds) {
      const metrics = origInk(el, ch);
      bounds = {left: own.left, right: own.left + metrics.width, top: own.top + metrics.dTop, bottom: own.top + metrics.dTop + metrics.height};
    }
    const stroke = reference * handwritingConfig.bracketStrokeScale;
    const height = Math.max(stroke * 4, bounds.bottom - bounds.top);
    const width = Math.max(stroke * 2, bounds.right - bounds.left);
    const sx = (width-stroke) / Math.max(shape.width, 1);
    const cap = Math.min(shape.capHeight, shape.height / 3);
    const sy = Math.min(sx, (height-stroke) / Math.max(2*cap,1));
    function transform(p) {
      const y = p[1] <= cap ? p[1] * sy : p[1] >= shape.height-cap ? height-stroke-(shape.height-p[1])*sy : cap*sy+(p[1]-cap)/(shape.height-2*cap)*(height-stroke-2*cap*sy);
      return [stroke/2+p[0]*sx, stroke/2+y];
    }
    const svg = makeSvg(width, height, 'hand-bracket');
    svg.dataset.sampleFamily = family; svg.dataset.referenceStroke = reference;
    svg.dataset.character = ch; svg.setAttribute('stroke-width', stroke);
    svg.style.left = (bounds.left-own.left)+'px'; svg.style.top = (bounds.top-own.top)+'px';
    const ink = getComputedStyle(el).color;
    svg.style.color = ink;
    addStroke(svg, shape.points.map(transform), stroke);
    el.style.position = 'relative'; el.style.color = 'transparent';
    Array.from(el.children).forEach(n => n.style.visibility = 'hidden');
    el.append(svg);
  }
}
function decorateMath(root) {
  if (!handwritingConfig.handMath) return;
  const content = root.querySelector('.katex-html');
  if (!content) return;
  const random = mkRand(textSeed(root.dataset.tex || root.textContent));
  decorateLetters(content, random, true);
  decorateVectors(root, random);
  decorateBrackets(root, random);
}
function auditHandwriting() {
  const audit = {fallbacks: [], structural: [], aliases: [], fonts: {}, brackets: [], vectors: []};
  function context(el) { return el.closest('[data-tex]')?.dataset.tex || el.closest('.hand-line')?.textContent || el.textContent; }
  document.querySelectorAll('.page .hand-glyph').forEach(el => {
    if (el.closest('[style*="visibility: hidden"]')) return;
    const record = {character: el.dataset.original, codepoint: el.dataset.codepoint, context: context(el)};
    if (el.dataset.fallback) audit.fallbacks.push({...record, reason: el.dataset.fallback});
    else audit.fonts[el.dataset.font] = (audit.fonts[el.dataset.font] || 0)+1;
    if (el.dataset.original !== el.dataset.character) audit.aliases.push({...record, renderedAs: el.dataset.character});
  });
  document.querySelectorAll('.page [data-handwriting-issue]').forEach(el => audit.structural.push({context: context(el), reason: el.dataset.handwritingIssue}));
  document.querySelectorAll('.page .hand-bracket').forEach(el => audit.brackets.push({character: el.dataset.character, family: el.dataset.sampleFamily, height: Number(el.getAttribute('height')), stroke: Number(el.getAttribute('stroke-width')), referenceStroke: Number(el.dataset.referenceStroke), context: context(el)}));
  document.querySelectorAll('.page .hand-vector-arrow').forEach(el => audit.vectors.push({family:el.dataset.sampleFamily,context:context(el)}));
  document.querySelectorAll('.page .op-symbol, .page .sqrt-sign, .page .stretchy').forEach(el => {
    if (!el.closest('.accent-body')) audit.structural.push({context:context(el),reason:'structural mathematical drawing retains KaTeX geometry'});
  });
  layoutReport.handwriting = audit;
}
