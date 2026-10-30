// Programmatic, headless acceptance only. No screenshots or physical UI claims.
// Uses an existing Playwright runtime via NODE_PATH; never installs a browser/package.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

(async () => {
  const source = path.resolve(process.argv[2]);
  const output = path.resolve('output/playwright/graphical-reports');
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1366, height: 768}, acceptDownloads: true});
  const errors = [], network = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.route(/^https?:/, route => {network.push(route.request().url()); return route.abort();});
  try {
    await page.goto(pathToFileURL(source).href);
    const root = page.locator('.uc-graphs');
    assert.equal(await root.count(), 1);
    const model = await root.locator('.uc-chart-data').evaluate(el => JSON.parse(el.textContent));
    assert.equal(model.groups.length, 6); // 3 measured counts x diagnostics off/on
    assert.equal(model.groups.reduce((n,g) => n + g.rows.length, 0), 36);
    assert.equal(model.groups.reduce((n,g) => n + g.rows.reduce((a,r)=>a+r.trials.length,0),0),108);
    let rendered = 0;
    for (let i=0;i<model.groups.length;i++) {
      await root.locator('select').selectOption(String(i));
      for (const metric of ['wall','speed','ram','pdf','phases','cpu']) {
        await root.locator(`[data-metric="${metric}"]`).click();
        const svg = root.locator('svg');
        if (metric==='cpu' && model.groups[i].diagnostics==='off') {
          assert.equal(await svg.count(), 0);
          assert.match(await root.locator('.uc-message').innerText(), /нет полного измеренного набора/);
        } else {
          assert.equal(await svg.count(), 1);
          assert.ok((await svg.locator('rect').count()) > 0);
          assert.ok((await svg.locator('title').first().textContent()).length > 3);
          rendered++;
        }
      }
    }
    await root.locator('[data-metric="wall"]').click();
    await root.locator('.uc-sort').click();
    assert.equal(await root.locator('.uc-sort').getAttribute('aria-pressed'),'true');
    await root.locator('summary').click();
    assert.ok((await root.locator('.uc-data tbody tr, .uc-data table tr').count()) >= 19);
    const downloadPromise = page.waitForEvent('download');
    await root.locator('.uc-save').click();
    const download = await downloadPromise;
    const svgFile = path.join(output,download.suggestedFilename());
    await download.saveAs(svgFile);
    assert.match(fs.readFileSync(svgFile,'utf8'), /<svg/);
    await page.setViewportSize({width:360,height:780});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    assert.deepEqual(network, []);
    assert.deepEqual(errors, []);
    const evidence = {scope:'headless browser; no visual/physical acceptance',groups:6,cases:36,trials:108,
      rendered_metric_views:rendered,cpu_off_is_not_zero:true,svg_download:true,mobile_body_overflow:false,
      network_requests:network.length,page_errors:errors,source};
    fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify(evidence,null,2));
    process.stdout.write(JSON.stringify(evidence)+'\n');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
