# Portal & Travel Studio assets

These are local production assets for the approved TravelMind visual direction.

- `portal-world.webp`: luminous mineral-glass doorway, used on the public homepage.
- `studio-environment.webp`: softly lit interior behind the trip workspace.
- `forest-flow.webp`: rain, forest, and warm light for the featured journey panel.
- `rain-window.webp`, `forest-cabin.webp`, `mist-lake.webp`: decorative trip covers, chosen deterministically from the trip ID. They do not identify or verify a destination; the collection UI discloses that they are AI concept art.
- `brand-mark.svg`: exported editable-vector brand mark from the approved Figma file `Ucx73tFmRGfSpUpSqOGTjR`.

The raster artwork was generated during this project's visual exploration, not copied from MotionSites templates. Images were resized and encoded as WebP; the app does not depend on temporary Figma asset URLs.

## Fonts

- Manrope Regular and SemiBold: self-hosted font files, SIL Open Font License 1.1. See `MANROPE-OFL.txt`.
- Noto Sans SC Light: self-hosted **text subset**, SIL Open Font License 1.1. See `NOTO-OFL.txt`. The subset covers the approved page copy. Other Chinese text, including user-supplied trip titles, falls back per glyph to PingFang SC or Microsoft YaHei. Regenerate the subset when changing display copy if exact font consistency is required.

Font source: the official Google Fonts repository. There are no runtime third-party font requests.
