# ICS logo

The mark keeps the motif of five connected nodes around a larger central point.
The lettering sits next to the symbol. A single solid colour and thicker
connections keep it legible at small sizes. The mark contains no fonts, filters
or embedded bitmaps.

## Files

Paths are relative to `frontend/public`.

| File | Use |
| --- | --- |
| `logo.svg` | Main symbol, from 32 px; geometry source for the other variants |
| `favicon.svg` | Optical variant for 16-31 px, larger nodes and the four main connections |
| `favicon.ico` | Favicon with 16, 32 and 48 px images |
| `favicon-16x16.png`, `favicon-32x32.png`, `favicon-48x48.png` | Favicon as PNG |
| `apple-touch-icon.png` | Opaque 180 x 180 px icon for the Apple home screen |
| `icons/app-icon.svg` | Vector app icon on a dark background |
| `icons/icon-192.png`, `icons/icon-512.png`, `icons/icon-1024.png` | App icons and exports for further use |
| `icons/app-icon-maskable.svg` | Vector icon with a margin for masking |
| `icons/icon-maskable-192.png`, `icons/icon-maskable-512.png` | `maskable` icons used by the manifest |
| `brand/logo-lockup.svg` | Symbol with the ICS lettering, for light backgrounds |
| `brand/logo-lockup-white.svg` | Symbol with white ICS lettering, for dark backgrounds |
| `brand/logo-mono.svg`, `brand/logo-white.svg` | Single-colour symbol for print and low-contrast backgrounds |
| `brand/index.html`, `brand/preview.png` | Sheet with the variants and their actual sizes |

## Usage

- Brand colour: `#FF5500`. Icon background and dark lettering: `#101419`.
- Minimum symbol size: 16 x 16 px, using `favicon.svg`.
- Full logo with lettering: at least 112 px wide.
- Keep the proportions and a clear space around the logo at least one small
  node wide, i.e. 12 units at `viewBox="0 0 64 64"`.
- On photos, use the single-colour mark on a solid, contrasting backdrop.
- Do not add letters inside the nodes, outlines or shadows.
- App icon files have a full, square background. The operating system applies
  the rounding; the rounded corners on the sheet only simulate that cropping.
- The whole symbol in the `maskable` version fits a circle with a radius of 40%
  of the side. The farthest point of the mark is at about 37.8% of the side,
  which leaves a margin.

In the app, the `BrandMark` component composes the symbol with a text ICS
label, which inherits the interface typeface and colour. The ready-made
`logo-lockup` files are for external materials; their lettering is geometry and
needs no font installed.

## Re-export

From `frontend/public`, with the project dependencies and Playwright's
Chromium installed:

```sh
node brand/export.mjs
```

The script reads `logo.svg`, regenerates the single-colour variants, the logo
with lettering and the app icons, then exports the PNG, ICO and the sheet.
`favicon.svg` has its own geometry, tuned by hand for small sizes. After a
geometry change, check the small sizes and the masking margin again.

## Verification

After a re-export, check the Chromium output on light and dark backgrounds at
16, 24, 32, 48 and 64 px, with both the circular and the rounded mask. The sheet
shows the 16 and 32 px rasters unscaled. Also check the SVG files parse as XML,
the PNG dimensions match the manifest, the ICO holds three sizes and the mark
stays inside the masking safe zone.

Technical requirements:
[maskable safe zone in the W3C spec](https://www.w3.org/TR/appmanifest/#icon-masks)
and [home screen icons in the Apple documentation](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/ConfiguringWebApplications/ConfiguringWebApplications.html).
