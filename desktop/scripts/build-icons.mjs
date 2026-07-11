// Rasterizes assets/logo.svg into assets/icons/{icon.ico,icon.icns,icon.png}.
// Pure npm pipeline (sharp + png2icons) -- no system ImageMagick/ffmpeg install needed.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';
import png2icons from 'png2icons';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, '..');
const svgPath = path.join(root, 'assets', 'logo.svg');
const outDir = path.join(root, 'assets', 'icons');

async function main() {
  fs.mkdirSync(outDir, { recursive: true });

  const sourcePng = await sharp(svgPath, { density: 384 })
    .resize(1024, 1024)
    .png()
    .toBuffer();

  const ico = png2icons.createICO(sourcePng, png2icons.BICUBIC2, 0, false, true);
  const icns = png2icons.createICNS(sourcePng, png2icons.BICUBIC2, 0);
  if (!ico || !icns) {
    throw new Error('png2icons failed to produce ico/icns output');
  }
  fs.writeFileSync(path.join(outDir, 'icon.ico'), ico);
  fs.writeFileSync(path.join(outDir, 'icon.icns'), icns);

  await sharp(sourcePng).resize(512, 512).toFile(path.join(outDir, 'icon.png'));

  console.log(`[build-icons] wrote icon.ico, icon.icns, icon.png to ${outDir}`);
}

main().catch((err) => {
  console.error('[build-icons] failed:', err);
  process.exit(1);
});
