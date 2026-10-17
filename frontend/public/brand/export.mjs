import { chromium } from 'playwright';
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const root = new URL('../', import.meta.url);
const master = await readFile(new URL('logo.svg', root), 'utf8');
const geometry = master.match(/<svg\b[^>]*>([\s\S]*)<\/svg>/)?.[1].trim();
if (!geometry) throw new Error('Cannot read logo.svg geometry');
const svg = (body, color = '#FF5500', viewBox = '0 0 64 64') =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" fill="none" color="${color}">\n${body}\n</svg>\n`;
for (const [name, color] of [['logo-mono', '#101419'], ['logo-white', '#FFFFFF']]) {
  await writeFile(new URL(`brand/${name}.svg`, root), svg(geometry, color));
}
for (const [name, scale] of [['app-icon', 0.84], ['app-icon-maskable', 0.72]]) {
  const offset = Number((32 * (1 - scale)).toFixed(2));
  await writeFile(new URL(`icons/${name}.svg`, root), svg(
    `<path fill="#101419" d="M0 0h64v64H0z"/>\n<g transform="translate(${offset} ${offset}) scale(${scale})">\n${geometry}\n</g>`,
  ));
}
const lettering = `<g fill="none" stroke="currentColor" stroke-width="6" stroke-linejoin="round">
  <path d="M84 16v32"/>
  <path d="M124 20c-3-3-6-4-10-4-9 0-14 6-14 16s5 16 14 16c4 0 7-1 10-4"/>
  <path d="M162 20c-3-3-7-4-12-4-7 0-12 3-12 8 0 12 25 4 25 16 0 5-5 8-12 8-6 0-11-2-14-5"/>
</g>`;
for (const [name, color] of [['logo-lockup', '#101419'], ['logo-lockup-white', '#FFFFFF']]) {
  await writeFile(new URL(`brand/${name}.svg`, root), svg(
    `<g color="#FF5500">${geometry}</g>\n${lettering}`, color, '0 0 174 64',
  ));
}
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  const jobs = [
    ...[16, 32, 48].map(size => ['favicon.svg', `favicon-${size}x${size}.png`, size]),
    ['icons/app-icon.svg', 'apple-touch-icon.png', 180],
    ...[192, 512, 1024].map(size => ['icons/app-icon.svg', `icons/icon-${size}.png`, size]),
    ...[192, 512].map(size => ['icons/app-icon-maskable.svg', `icons/icon-maskable-${size}.png`, size]),
  ];
  for (const [source, target, size] of jobs) {
    const svg = await readFile(new URL(source, root), 'utf8');
    const png = await page.evaluate(async ({ svg, size }) => {
      const image = new Image();
      image.src = `data:image/svg+xml;base64,${btoa(svg)}`;
      await image.decode();
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = size;
      canvas.getContext('2d').drawImage(image, 0, 0, size, size);
      return canvas.toDataURL('image/png').split(',')[1];
    }, { svg, size });
    await writeFile(new URL(target, root), Buffer.from(png, 'base64'));
    console.log(target);
  }

  // PNG entries preserve alpha at each native favicon size.
  const sizes = [16, 32, 48];
  const images = await Promise.all(sizes.map(size => readFile(new URL(`favicon-${size}x${size}.png`, root))));
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach((png, index) => {
    const entry = 6 + index * 16;
    header[entry] = header[entry + 1] = sizes[index];
    header.writeUInt16LE(1, entry + 4);
    header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(png.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += png.length;
  });
  await writeFile(new URL('favicon.ico', root), Buffer.concat([header, ...images]));

  await page.setViewportSize({ width: 1200, height: 1200 });
  await page.goto(new URL('brand/index.html', root).href);
  await page.evaluate(() => Promise.all([...document.images].map(image => image.decode())));
  await page.screenshot({ path: fileURLToPath(new URL('brand/preview.png', root)), fullPage: true });
  console.log('favicon.ico, brand/preview.png');
} finally {
  await browser.close();
}
