// Local helper for https://pdf-lib.js.org/docs/api/classes/pdfdocument
// Keep file paths in UTF-8 JSON rather than expanding 1000 paths into argv.
import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';

const require = createRequire(process.env.UCODE_ASSET_ROOT ? resolve(process.env.UCODE_ASSET_ROOT, 'package.json') : import.meta.url);
const { PDFDocument } = require('pdf-lib');

async function main() {
  if (process.argv.length !== 3) {
    throw new Error('Usage: node merge-pdflib.mjs INPUTS.json');
  }
  const request = JSON.parse(await readFile(process.argv[2], 'utf8'));
  if (!Array.isArray(request.inputs) || request.inputs.length === 0
      || request.inputs.some(path => typeof path !== 'string' || !path)
      || typeof request.output !== 'string' || !request.output) {
    throw new Error('Expected nonempty inputs and an output path in the manifest');
  }
  const result = await PDFDocument.create({ updateMetadata: false });
  for (const input of request.inputs) {
    const source = await PDFDocument.load(await readFile(input), { updateMetadata: false });
    const pages = await result.copyPages(source, source.getPageIndices());
    for (const page of pages) result.addPage(page);
  }
  const bytes = await result.save({ useObjectStreams: true, addDefaultPage: false, updateFieldAppearances: false });
  // Exclusive creation protects a target that appeared after the Python guard.
  await writeFile(request.output, bytes, { flag: 'wx' });
}

main().catch(error => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
