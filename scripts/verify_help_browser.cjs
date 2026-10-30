// Existing bundled runtime only. Headless DOM checks; no screenshots or installs.
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{
 const file=path.resolve(process.argv[2]),browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1366,height:768}}),errors=[],network=[];
 page.on('pageerror',e=>errors.push(String(e)));
 await page.route(/^https?:/,route=>{network.push(route.request().url());return route.abort()});
 try{
  await page.goto(pathToFileURL(file).href+'#queue');
  assert.equal(await page.locator('main section').count(),13);
  assert.equal(await page.locator('img').evaluate(i=>i.complete&&i.naturalWidth>0),true);
  await page.locator('#search').fill('прогрев');
  assert.ok(await page.locator('main section:visible').count()>0);
  assert.equal(await page.locator('#tests').isVisible(),true);
  await page.locator('#search').fill('ничего-не-найдётся-739');
  assert.equal(await page.locator('#empty').isVisible(),true);
  await page.evaluate(()=>{location.hash='print'});await page.waitForFunction(()=>!document.getElementById('print').hidden);
  assert.equal(await page.locator('#search').inputValue(),'');
  await page.locator('#demo-module').fill('1');await page.locator('#demo-quiet').fill('6');
  assert.match(await page.locator('#qr-summary').innerText(),/33 мм/);
  await page.locator('#demo-count').fill('10000');await page.locator('#demo-cpus').fill('14');
  await page.locator('#demo-factor').selectOption('2');await page.locator('#demo-batch').selectOption('50');
  assert.match(await page.locator('#queue-summary').innerText(),/200 порций · 14 CPU · 28 процессов/);
  assert.equal(await page.locator('#queue-drawing svg rect').count(),14);
  await page.evaluate(()=>{Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text}},configurable:true})});
  await page.locator('[data-copy="command-0"]').click();
  assert.match(await page.evaluate(()=>window.copied),/^test pipeline --codes 3/);
  for(const width of [1366,780,360]){await page.setViewportSize({width,height:768});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),String(width))}
  assert.deepEqual(network,[]);assert.deepEqual(errors,[]);
  const proof={sections:13,logo:'loaded',search:'PASS',anchors:'PASS',queue:'10000 / 50 = 200 packets; 14 CPU / 28 processes',qr:'33mm at module1/quiet6',copy:'PASS',viewports:[1366,780,360],network_requests:network.length,js_errors:errors,visual_acceptance:'USER-CHECK'};
  fs.mkdirSync('output/help-ux',{recursive:true});fs.writeFileSync('output/help-ux/browser-proof.json',JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
