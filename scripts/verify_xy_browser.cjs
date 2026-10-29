// Headless DOM/SVG checks. Existing runtime only; no screenshots or installs.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {pathToFileURL}=require('node:url'),{chromium}=require('playwright');
(async()=>{
 const proof=JSON.parse(fs.readFileSync(process.argv[2],'utf8').replace(/^\uFEFF/,''));
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1366,height:768},acceptDownloads:true});
 const errors=[],network=[];page.on('pageerror',e=>errors.push(String(e)));await page.route(/^https?:/,r=>{network.push(r.request().url());return r.abort();});
 try{
  await page.goto(pathToFileURL(proof.control).href);
  const root=page.locator('.uc-graphs');await root.locator('[data-metric="xy"]').click();
  assert.equal(await root.locator('svg').count(),1);
  const data=await root.locator('.uc-chart-data').evaluate(n=>JSON.parse(n.textContent));
  assert.deepEqual(data.timelines[0].points,[[0,0,null,0],[1,100,100,1],[3,500,200,2],[4,500,0,1]]);
  const points=await root.locator('svg circle').evaluateAll(ns=>ns.map(n=>[+n.getAttribute('cx'),+n.getAttribute('cy')]));
  assert.equal(points.length,3);assert.equal((points[1][0]-points[0][0])/(points[2][0]-points[1][0]),2);
  const text=await root.locator('svg').textContent();assert.match(text,/минимум 0.*средняя по времени 125.*пик 200/);
  assert.match(text,/Сверху: фактическое количество/);assert.match(text,/прошедшее время/);
  const downloadPromise=page.waitForEvent('download');await root.locator('.uc-save').click();const download=await downloadPromise;
  const output=path.resolve('output/playwright/xy-reports');fs.mkdirSync(output,{recursive:true});await download.saveAs(path.join(output,'control.svg'));
  await page.goto(pathToFileURL(proof.production).href);
  assert.equal(await root.locator('[data-metric="xy"]').getAttribute('aria-pressed'),'true');
  assert.equal(await root.locator('.uc-xy-choice select option').count(),2);
  for(const option of ['0','1']){await root.locator('.uc-xy-choice select').selectOption(option);assert.equal(await root.locator('svg').count(),1);}
  await page.goto(pathToFileURL(proof.queue).href);await root.locator('[data-metric="xy"]').click();
  assert.ok((await root.locator('.uc-xy-choice select option').count())>=3);
  await page.setViewportSize({width:360,height:780});
  // SVG may scroll inside its container; the browser body should not.
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
  assert.equal(overflow,false);
  assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
  const result={scope:'headless XY, no visual acceptance',nonuniform_time_geometry:true,real_count_ticks:true,
   weighted_stats:true,production_and_queue:true,svg_export:true,network_requests:0,page_errors:[],mobile_body_overflow:false};
  fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
