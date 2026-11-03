// Responsive, locally generated imagery for the homepage's below-fold sections.
const IMAGES = {
  "service-airport": { width: 1110, height: 1200, widths: [320, 480, 640, 960, 1110] },
  "service-corporate": { width: 1110, height: 1200, widths: [320, 480, 640, 960, 1110] },
  "service-sprinter": { width: 1110, height: 1200, widths: [320, 480, 640, 960, 1110] },
  "how-trip": { width: 1200, height: 800, widths: [360, 640, 960, 1200] },
  "how-vehicle": { width: 1200, height: 800, widths: [360, 640, 960, 1200] },
  "how-pro": { width: 1200, height: 800, widths: [360, 640, 960, 1200] },
  "austin-skyline": { width: 622, height: 1140, widths: [200, 311, 400, 622] },
  "austin-capitol": { width: 498, height: 560, widths: [160, 249, 320, 498] },
  "austin-pickup": { width: 498, height: 560, widths: [160, 249, 320, 498] },
} as const;

export type HomepageImageKey = keyof typeof IMAGES;

export default function HomepagePicture({ image, alt, sizes }: {
  image: HomepageImageKey;
  alt: string;
  sizes: string;
}) {
  const { width, height, widths } = IMAGES[image];
  const base = `/assets/imgs/page/homepage1/${image}`;
  const srcSet = (format: string) => widths.map((w) => `${base}-${w}.${format} ${w}w`).join(", ");

  return (
    <picture>
      <source type="image/avif" srcSet={srcSet("avif")} sizes={sizes} />
      <source type="image/webp" srcSet={srcSet("webp")} sizes={sizes} />
      <img src={`${base}.webp`} alt={alt} width={width} height={height} loading="lazy" decoding="async" />
    </picture>
  );
}
