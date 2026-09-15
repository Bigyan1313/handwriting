// One seeded generator, shared by every layer that makes a random choice, so a
// given --seed reproduces a render exactly: the same line offsets, the same
// glyph variants, the same bracket samples.
//
// Loaded before layout.js, which calls this while it is being read.
function mkRand(seed) {
  var s = seed >>> 0;
  return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}
