// Swap KaTeX's stretchy delimiters for handwritten ones.
//
// KaTeX draws tall brackets as SVG paths rather than glyphs, so they cannot be
// font-swapped the way letters are. Instead the matching character is read out
// of the LaTeX source in order, its drawn box is measured, and the handwritten
// glyph is scaled to cover the same box.
//
// Square brackets are handled by handwriting.js instead, from traced sample
// centrelines, so they are skipped here.
//
// Runtime values arrive in `delimiterConfig`:
//   enabled      whether to run at all (needs a custom font and --hand-math)
//   variants     font families to pick a delimiter glyph from
//   seed         so the picks are reproducible
//   fontAscent   the custom font's ascent and units-per-em, used to put the
//   fontUpem     scaled glyph on the right baseline

var DELIM_MAP = {'\\{': '{', '\\}': '}', '\\|': '|', '\\lbrack': '[',
                 '\\rbrack': ']', '\\vert': '|', '\\Vert': '|',
                 '[': '[', ']': ']', '(': '(', ')': ')', '|': '|'};

var ENV_DELIMS = {
  'pmatrix': ['(', ')'],
  'bmatrix': ['[', ']'],
  'Bmatrix': ['{', '}'],
  'vmatrix': ['|', '|'],
  'Vmatrix': ['|', '|'],
  'cases':   ['{', null],
  'dcases':  ['{', null],
  'rcases':  [null, '}'],
  'drcases': [null, '}']
};

function delimsFromTex(tex) {
  var out = [];
  var re = /\\(?:(left|right)(?![a-zA-Z])\s*(\\[a-zA-Z]+|\\[^a-zA-Z\s]|[^\s])|(begin|end)\{([a-zA-Z]+)\})/g;
  var m;
  while ((m = re.exec(tex)) !== null) {
    if (m[1]) {
      var raw = m[2];
      if (raw === '.') continue;
      out.push(DELIM_MAP[raw] || (raw.length === 1 ? raw : null));
    } else if (m[3]) {
      var action = m[3];
      var env = m[4];
      if (ENV_DELIMS[env]) {
        var ch = action === 'begin' ? ENV_DELIMS[env][0] : ENV_DELIMS[env][1];
        if (ch) out.push(ch);
      }
    }
  }
  return out;
}

function inkMetrics(ch, family, size) {
  var cx = document.createElement('canvas').getContext('2d');
  cx.font = size + "px '" + family + "'";
  var m = cx.measureText(ch);
  return {asc: m.actualBoundingBoxAscent, desc: m.actualBoundingBoxDescent,
          left: m.actualBoundingBoxLeft, right: m.actualBoundingBoxRight};
}

// A .delimsizing box doesn't cover the pieces it draws (they overflow it),
// so take the union of its descendants' boxes.
function visualRect(el) {
  var r = el.getBoundingClientRect();
  var top = r.top, bot = r.bottom, left = r.left, right = r.right;
  el.querySelectorAll('*').forEach(function (n) {
    var b = n.getBoundingClientRect();
    if (!b.height || !b.width) return;
    top = Math.min(top, b.top); bot = Math.max(bot, b.bottom);
    left = Math.min(left, b.left); right = Math.max(right, b.right);
  });
  return {dTop: top - r.top, dLeft: left - r.left, height: bot - top, width: right - left};
}

// Also used by handwriting.js, for a small bracket that overflows its own box.
function origInk(el, ch) {
  var cs = getComputedStyle(el);
  var cx = document.createElement('canvas').getContext('2d');
  cx.font = parseFloat(cs.fontSize) + 'px ' + cs.fontFamily;
  var m = cx.measureText(ch);
  var probe = document.createElement('span');
  probe.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline;';
  el.appendChild(probe);
  var by = probe.getBoundingClientRect().top;   // sits on the text baseline
  probe.remove();
  var r = el.getBoundingClientRect();
  var h = m.actualBoundingBoxAscent + m.actualBoundingBoxDescent;
  var w = m.actualBoundingBoxLeft + m.actualBoundingBoxRight;
  return {dTop: (by - m.actualBoundingBoxAscent) - r.top, dLeft: 0,
          height: h, width: Math.max(w, r.width)};
}

function handDelims(root, pick) {
  var wanted = delimsFromTex(root.dataset.tex || '');
  Array.from(root.querySelectorAll('.delimsizing')).forEach(function (el, i) {
    var ch = (el.textContent || '').replace(/[\u200b\s]/g, '');
    if (!ch) ch = wanted[i] || null;
    if (!ch || '[]{}()|'.indexOf(ch) < 0 || ch === '[' || ch === ']') return;
    var pc = el.parentElement ? String(el.parentElement.className) : '';
    if ('([{'.indexOf(ch) >= 0 && pc.indexOf('mclose') >= 0) return;
    if (')]}'.indexOf(ch) >= 0 && pc.indexOf('mopen') >= 0) return;
    // Tall delimiters are drawn as child SVG/vlist pieces (union their
    // boxes). Small ones are a bare text glyph that overflows its own box,
    // so measure that glyph's ink against the element's baseline instead.
    var v = el.children.length ? visualRect(el) : origInk(el, ch);
    if (!v || !v.height) return;
    var fam = pick();
    var S = 100, im = inkMetrics(ch, fam, S);
    var inkH = im.asc + im.desc, inkW = im.left + im.right;
    if (!inkH || !inkW) return;
    var sy = v.height / inkH;
    var sx = Math.min(v.width / inkW, sy);
    var baseOff = -S / 2 + S * delimiterConfig.fontAscent / delimiterConfig.fontUpem;
    var tx = v.dLeft + im.left * sx;
    var ty = v.dTop - (baseOff - im.asc) * sy;
    el.style.position = 'relative';
    // Small delimiters are a bare text node on the element itself; tall ones
    // are child SVG/vlist pieces. Hide both kinds before drawing over them.
    var ink = getComputedStyle(el).color;
    el.style.color = 'transparent';
    Array.from(el.children).forEach(function (c) { c.style.visibility = 'hidden'; });
    var g = document.createElement('span');
    g.textContent = ch;
    g.style.cssText = "position:absolute;left:0;top:0;display:block;line-height:0;color:" + ink + ";"
      + "font-family:'" + fam + "';font-size:" + S + "px;white-space:pre;"
      + "transform-origin:0 0;transform:translate(" + tx + "px," + ty + "px) scale("
      + sx + "," + sy + ");";
    el.appendChild(g);
  });
}

function applyHandDelimiters() {
  if (!delimiterConfig.enabled) return;
  var dr = mkRand(delimiterConfig.seed + 7919);
  var variants = delimiterConfig.variants;
  var pick = function () { return variants[Math.floor(dr() * variants.length)]; };
  document.querySelectorAll('.math-src, .display-math-src').forEach(function (root) {
    try { handDelims(root, pick); } catch (e) {}
  });
}
