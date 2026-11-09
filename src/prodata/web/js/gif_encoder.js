// GIF animado sem biblioteca externa (spec 030): paleta única por corte mediano e compressão LZW.
// Pixels iguais aos do quadro anterior ficam transparentes, o que reduz muito o arquivo em gráficos.

const COLORS = 255; // o índice 255 é o transparente
const TRANSPARENT = 255;
const key15 = (r, g, b) => ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);

function histogram(samples) {
  const counts = new Map();
  for (const data of samples) {
    for (let i = 0; i < data.length; i += 4) {
      const k = key15(data[i], data[i + 1], data[i + 2]);
      const entry = counts.get(k);
      if (entry) { entry.n += 1; entry.r += data[i]; entry.g += data[i + 1]; entry.b += data[i + 2]; }
      else counts.set(k, { n: 1, r: data[i], g: data[i + 1], b: data[i + 2] });
    }
  }
  return [...counts.values()].map((e) => ({ n: e.n, r: e.r / e.n, g: e.g / e.n, b: e.b / e.n }));
}

function spreadOf(box) {
  const range = (ch) => {
    const values = box.map((e) => e[ch]);
    return Math.max(...values) - Math.min(...values);
  };
  const channels = ['r', 'g', 'b'].map((ch) => [ch, range(ch)]).sort((a, b) => b[1] - a[1]);
  return { channel: channels[0][0], spread: channels[0][1] };
}

/** Corte mediano: divide sempre a caixa com mais peso e maior variação. */
export function buildPalette(samples) {
  let boxes = [histogram(samples)];
  while (boxes.length < COLORS) {
    let best = -1;
    let bestScore = 0;
    boxes.forEach((box, i) => {
      if (box.length < 2) return;
      const score = spreadOf(box).spread * box.reduce((acc, e) => acc + e.n, 0);
      if (score > bestScore) { bestScore = score; best = i; }
    });
    if (best < 0) break;
    const box = boxes[best];
    const { channel } = spreadOf(box);
    box.sort((a, b) => a[channel] - b[channel]);
    const half = box.reduce((acc, e) => acc + e.n, 0) / 2;
    let seen = 0;
    let cut = 1;
    for (let i = 0; i < box.length - 1; i += 1) {
      seen += box[i].n;
      cut = i + 1;
      if (seen >= half) break;
    }
    boxes = [...boxes.slice(0, best), box.slice(0, cut), box.slice(cut), ...boxes.slice(best + 1)];
  }
  return boxes.map((box) => {
    const total = box.reduce((acc, e) => acc + e.n, 0);
    const avg = (ch) => Math.round(box.reduce((acc, e) => acc + e[ch] * e.n, 0) / total);
    return [avg('r'), avg('g'), avg('b')];
  });
}

function nearestFinder(palette) {
  const cache = new Int16Array(32768).fill(-1);
  return (r, g, b) => {
    const k = key15(r, g, b);
    if (cache[k] >= 0) return cache[k];
    let best = 0;
    let bestD = Infinity;
    for (let i = 0; i < palette.length; i += 1) {
      const [pr, pg, pb] = palette[i];
      const d = (pr - r) ** 2 + (pg - g) ** 2 + (pb - b) ** 2;
      if (d < bestD) { bestD = d; best = i; }
    }
    cache[k] = best;
    return best;
  };
}

class ByteWriter {
  constructor() { this.chunks = []; this.buffer = new Uint8Array(65536); this.pos = 0; }

  byte(v) {
    if (this.pos === this.buffer.length) this.flush();
    this.buffer[this.pos] = v;
    this.pos += 1;
  }

  word(v) { this.byte(v & 255); this.byte((v >> 8) & 255); }

  bytes(list) { for (const v of list) this.byte(v); }

  flush() {
    this.chunks.push(this.buffer.slice(0, this.pos));
    this.pos = 0;
  }
}

/** LZW de tamanho variável, no formato do GIF. */
function compress(indices, out) {
  const CLEAR = 256;
  const END = 257;
  const HSIZE = 5003;
  const htab = new Int32Array(HSIZE).fill(-1);
  const codes = new Int32Array(HSIZE);
  let bits = 9;
  let maxcode = 511;
  let free = 258;
  let clearing = false;
  let accum = 0;
  let accumBits = 0;
  const block = new Uint8Array(255);
  let blockLen = 0;
  const pushByte = (v) => {
    block[blockLen] = v;
    blockLen += 1;
    if (blockLen === 255) { out.byte(255); out.bytes(block); blockLen = 0; }
  };
  const emit = (code) => {
    accum |= code << accumBits;
    accumBits += bits;
    while (accumBits >= 8) { pushByte(accum & 255); accum >>>= 8; accumBits -= 8; }
    if (free > maxcode || clearing) {
      if (clearing) { bits = 9; maxcode = 511; clearing = false; }
      else { bits += 1; maxcode = bits === 12 ? 4096 : (1 << bits) - 1; }
    }
  };
  out.byte(8);
  emit(CLEAR);
  let ent = indices[0];
  for (let i = 1; i < indices.length; i += 1) {
    const c = indices[i];
    const fcode = (c << 12) + ent;
    let h = ((c << 4) ^ ent) % HSIZE;
    let found = false;
    const step = h === 0 ? 1 : HSIZE - h;
    while (htab[h] >= 0) {
      if (htab[h] === fcode) { ent = codes[h]; found = true; break; }
      h -= step;
      if (h < 0) h += HSIZE;
    }
    if (found) continue;
    emit(ent);
    ent = c;
    if (free < 4096) {
      codes[h] = free;
      free += 1;
      htab[h] = fcode;
    } else {
      htab.fill(-1);
      free = 258;
      clearing = true;
      emit(CLEAR);
    }
  }
  emit(ent);
  emit(END);
  while (accumBits > 0) { pushByte(accum & 255); accum >>>= 8; accumBits -= 8; }
  if (blockLen) { out.byte(blockLen); out.bytes(block.subarray(0, blockLen)); }
  out.byte(0);
}

function writeHeader(out, width, height, palette, loop) {
  out.bytes([71, 73, 70, 56, 57, 97]); // GIF89a
  out.word(width);
  out.word(height);
  out.byte(0xf7); // tabela global de 256 cores
  out.byte(0);
  out.byte(0);
  for (let i = 0; i < 256; i += 1) out.bytes(palette[i] || [0, 0, 0]);
  if (loop) {
    out.bytes([0x21, 0xff, 11, 78, 69, 84, 83, 67, 65, 80, 69, 50, 46, 48, 3, 1]);
    out.word(0); // 0 = repetir sempre
    out.byte(0);
  }
}

function writeFrame(out, indices, width, height, delayCs) {
  out.bytes([0x21, 0xf9, 4, 0x05]); // transparência ligada, manter o quadro anterior
  out.word(delayCs);
  out.byte(TRANSPARENT);
  out.byte(0);
  out.byte(0x2c);
  out.word(0);
  out.word(0);
  out.word(width);
  out.word(height);
  out.byte(0);
  compress(indices, out);
}

/**
 * Monta o arquivo. `next()` devolve os pixels RGBA de cada quadro, um por vez, para não guardar todos na memória.
 * `samples` são alguns quadros já desenhados, que definem a paleta.
 */
export async function encodeGif({ width, height, count, delayCs, loop, samples, next, progress }) {
  const palette = buildPalette(samples);
  const nearest = nearestFinder(palette);
  const out = new ByteWriter();
  writeHeader(out, width, height, palette, loop);
  const size = width * height;
  let previous = null;
  for (let f = 0; f < count; f += 1) {
    const data = await next(f);
    if (!data) return null; // cancelado
    const indices = new Uint8Array(size);
    for (let i = 0; i < size; i += 1) {
      const p = i * 4;
      const color = nearest(data[p], data[p + 1], data[p + 2]);
      indices[i] = previous && previous[i] === color ? TRANSPARENT : color;
    }
    const current = indices.map((v, i) => (v === TRANSPARENT ? previous[i] : v));
    writeFrame(out, indices, width, height, delayCs);
    previous = current;
    progress?.(f + 1);
  }
  out.byte(0x3b);
  out.flush();
  return new Blob(out.chunks, { type: 'image/gif' });
}
