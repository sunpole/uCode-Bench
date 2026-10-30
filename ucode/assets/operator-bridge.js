// Inserted inside the approved renderer's closure. Styles/layout are not rebuilt.
let rtState=null,rtLoading=false,rtHydrating=false,rtFormTimer=null,rtPollTimer=null,rtRenderToken=0;
let rtSourceDigest='',rtChoice='all',rtNonce=null,rtConfigs={},rtFormError='',rtArchivePage=0,rtHistoryPage=0;
let rtConfigSequence=Promise.resolve(),rtScientificOptions={size:200,methods:[]};
const rtToken=location.pathname.split('/').filter(Boolean)[0],rtBase=location.pathname.replace(/\/?$/,'/');
const rtClone=value=>JSON.parse(JSON.stringify(value));
Object.assign(valueNames,{full:'Полная',vector:'Структура PDF',deferred:'Без проверки',multipage:'Один PDF',singles:'Отдельные PDF',both:'Оба варианта',white:'Белый',color:'Цветной',transparent:'Прозрачный',staged:'С отбором',true:'Вкл',false:'Выкл','all-2':'Все −2',all:'Все'});
fieldNames.print_settings='Настройки PDF теста';
const rtNumber=value=>Number(String(value).replace(/\s/g,'').replace(',','.'));
const rtText=(node,text)=>{if(node&&node.textContent!==String(text))node.textContent=String(text);};
const rtClock=seconds=>{seconds=Math.max(0,Math.floor(seconds||0));return [Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].map(n=>String(n).padStart(2,'0')).join(':');};
const rtBytes=n=>Number.isFinite(n)?(n/1024**2).toFixed(2)+' МиБ':'—';
async function rtAPI(route,value){
  const options=value===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-UCode-Token':rtToken},body:JSON.stringify(value)};
  const response=await fetch(rtBase+'api/'+route,options);const data=await response.json();
  if(!response.ok)throw Error(data.error||'Ошибка локального процесса');return data;
}
function rtError(error){rtText($('uc-status'),error.message||error);if(String(error.message).includes('PATH_REQUIRED'))activateTab(5);}
async function rtAction(route,value={}){
  if(rtLoading)return;rtLoading=true;
  try{const data=await rtAPI(route,value);if(data&&'busy'in data)rtApplyState(data);return data;}
  catch(error){rtError(error);throw error;}finally{rtLoading=false;}
}
function rtButton(parent,text,action,note=''){
  const button=el('button',text);button.type='button';button.dataset.tooltip=note||text;
  button.onclick=()=>Promise.resolve().then(action).catch(rtError);parent.append(button);return button;
}
function rtCycleValue(key,wanted){
  const button=panels[3].querySelector('[data-uc-setting="'+key+'"]')||baseOpen.querySelector('[data-uc-setting="'+key+'"]');
  if(!button||button.tagName!=='BUTTON')return;
  for(let n=0;n<8&&orderSettings[key]!==wanted;n++)button.onclick();
}
function rtCPUButtons(){
  if(!rtState)return;const cpu=rtState.hardware.cpu;
  const physical=orderSettings.cpu_unit!=='Потоки SMT',maximum=(physical?cpu.available_physical:cpu.available_logical)||cpu.available_logical;
  const row=$('uc-cpu');row.replaceChildren(el('span',physical?'Ядра:':'Потоки SMT:'));
  [['1','1'],...(maximum>2?[['all-2','Все − 2 · '+(maximum-2)]]:[]),['all','Все · '+maximum]].forEach(([choice,label])=>{
    const button=el('button',label);button.type='button';button.dataset.cpu=choice==='all'?maximum:choice==='all-2'?maximum-2:1;
    button.setAttribute('aria-pressed',String(rtChoice===choice));button.dataset.tooltip='Реальные '+(physical?'физические ядра':'логические CPU')+' текущего ПК';
    button.onclick=event=>{event.stopPropagation();rtSelectCPU(choice);};row.append(button);
  });
  const info=panels[3].querySelector('.uc-small');
  rtText(info,(cpu.name||'CPU')+' · '+cpu.physical_cores+' ядер / '+cpu.logical_processors+' потоков · доступно '+(cpu.available_physical||'?')+' / '+cpu.available_logical+' · RAM '+(rtState.hardware.ram.available_bytes/1024**3).toFixed(1)+' ГиБ свободно');
}
function rtSelectCPU(choice){
  if(rtHydrating||!rtState)return;
  try{
    const unit=orderSettings.cpu_unit==='Потоки SMT'?'logical':'physical';
    const selected=window.ucodeOperatorControls.cpuSelection(rtState.hardware.cpu,unit,choice);
    rtChoice=selected.choice;state.cpu=selected.workers;customCPU.value=workersControl.value=String(selected.workers);affinityField.value='';
    $('uc-method').selectedIndex=0;$('uc-method').dispatchEvent(new Event('change',{bubbles:true}));
    rtCPUButtons();rtQueueForm();
  }catch(error){rtChoice=String(choice);rtFormError=error.message;updatePathGate();rtError(error);}
}
function rtHydrate(data){
  rtHydrating=true;
  try{
    const f=data.form,p=f.print;rtChoice=f.cpu_choice;state.cpu=f.workers;customCPU.value=f.cpu_choice==='all'||f.cpu_choice==='all-2'?f.workers:f.cpu_choice==='legacy'?f.workers:f.cpu_choice;workersControl.value=f.workers;
    $('uc-side').value=String(p.module_mm*(21+2*p.quiet_modules));moduleControl.value=String(p.module_mm);
    const quietField=panels[2].querySelector('input[aria-label^="Белое поле"]');if(quietField)quietField.value=p.quiet_modules;
    if(![...quietPicker.options].some(o=>parseInt(o.value,10)===p.quiet_modules)){const option=el('option',p.quiet_modules+' модуля');quietPicker.append(option);}
    quietPicker.selectedIndex=[...quietPicker.options].findIndex(o=>parseInt(o.value,10)===p.quiet_modules);
    inkInputs.forEach((input,i)=>input.value=p.ink[i]);copiesField.value=f.copies_per_value;
    backgroundMode=['white','color','transparent'].indexOf(p.background_mode||'white');backgroundInputs.forEach((input,i)=>input.value=(p.background_ink||[0,0,0,0])[i]);
    bgMode.textContent=['ФОН: БЕЛЫЙ','ФОН: ЦВЕТНОЙ','ФОН: ПРОЗРАЧНЫЙ'][backgroundMode];bgInputsWrap.hidden=backgroundMode!==1;
    pathInput.value=f.output_directory;$('uc-output').selectedIndex=['multipage','singles','both'].indexOf(f.mode);
    $('uc-ram').selectedIndex={auto:0,max:1,'50%':2,'80%':3}[f.ram_mode]??0;
    $('uc-qa').selectedIndex=f.qa_mode==='deferred'?0:1;$('uc-statistics').selectedIndex=f.telemetry==='off'?0:1;
    $('uc-method').selectedIndex={process:0,serial:2,thread:3}[f.execution_backend]??0;
    rtCycleValue('cpu_unit',f.cpu_unit==='logical'?'Потоки SMT':'Физические ядра');
    rtCycleValue('activity',f.activity==='minimal'?'Минимальные':'Обычные');rtCycleValue('pdf_profile',p.pdf_profile==='compact'?'Компактный':'Обычный');
    rtCycleValue('timeline_mode',f.timeline_mode==='on'?'Записывать':'Выключен');rtCycleValue('qa_depth',f.qa_mode==='vector'?'Структура без растра':'Полная');
    rtCycleValue('duplicate_policy',f.duplicate_policy==='unique'?'Один экземпляр значения':'Сохранить строки');
    const batch=advancedSettings.querySelector('input[aria-label="Количество кодов в одной порции"]');if(batch)batch.value=f.batch_size;
    affinityField.value=(f.manual_cpus||[]).join(', ');
    Object.assign(state,data.ui);state.rowFont=data.ui.rowFont||8;state.theme=data.ui.theme||'dark';
    const sequence=data.ui.sequence||{start:'500000000000',count:f.template_count,step:1};
    $('uc-start').value=sequence.start;$('uc-total').value=sequence.count;$('uc-step').value=sequence.step;calc();
    if(statsExpanded!==data.ui.statisticsOpen){statsExpanded=data.ui.statisticsOpen!==false;applyStatsFold();}
    applyAppearance();applyTextSelection();cycleControls.forEach(sync=>sync());rtCPUButtons();fitPreview();applyBackground();
    numericInputs.forEach(groupInput);
  }finally{rtHydrating=false;}
}
function rtCollectForm(){
  if(!rtState)throw Error('Программа ещё загружается');
  const f=rtClone(rtState.form),quiet=rtNumber(panels[2].querySelector('input[aria-label^="Белое поле"]').value);
  f.print={module_mm:rtNumber($('uc-side').value)/(21+2*quiet),quiet_modules:quiet,ink:inkInputs.map(input=>rtNumber(input.value)),
    pdf_profile:orderSettings.pdf_profile==='Компактный'?'compact':'standard',background_mode:['white','color','transparent'][backgroundMode],background_ink:backgroundInputs.map(input=>rtNumber(input.value))};
  f.mode=['multipage','singles','both'][$('uc-output').selectedIndex];f.copies_per_value=rtNumber(copiesField.value);
  f.duplicate_policy=orderSettings.duplicate_policy==='Один экземпляр значения'?'unique':'preserve';f.output_directory=pathInput.value;
  f.execution_backend={0:'process',2:'serial',3:'thread'}[$('uc-method').selectedIndex]||'process';
  f.cpu_unit=orderSettings.cpu_unit==='Потоки SMT'?'logical':'physical';f.cpu_choice=f.execution_backend==='process'?rtChoice:'legacy';
  f.workers=rtNumber(workersControl.value);f.ram_mode=['auto','max','50%','80%','auto'][$('uc-ram').selectedIndex];
  f.qa_mode=$('uc-qa').selectedIndex===0?'deferred':orderSettings.qa_depth==='Структура без растра'?'vector':'full';
  f.activity=orderSettings.activity==='Минимальные'?'minimal':'normal';f.timeline_mode=orderSettings.timeline_mode==='Выключен'?'off':'on';
  f.telemetry=$('uc-statistics').selectedIndex===1?'cpu':'off';
  const batch=advancedSettings.querySelector('input[aria-label="Количество кодов в одной порции"]');f.batch_size=rtNumber(batch.value);
  f.manual_cpus=affinityField.value.split(/[,;\s]+/).filter(Boolean);if(f.manual_cpus.length)f.cpu_choice='legacy';
  return f;
}
async function rtFlushForm(){
  clearTimeout(rtFormTimer);rtFormTimer=null;if(!rtState||rtHydrating)return;
  const value=rtCollectForm();const next=rtConfigSequence.catch(()=>{}).then(()=>rtAPI('configure',value));rtConfigSequence=next;
  const data=await next;rtFormError='';rtApplyState(data);return data;
}
function rtQueueForm(){
  if(rtHydrating||runActive||!rtState)return;
  approvedPath=false;launchButton.classList.add('uc-path-blocked');clearTimeout(rtFormTimer);
  rtFormTimer=setTimeout(()=>rtFlushForm().then(()=>render()).catch(error=>{rtFormError=error.message;rtError(error);}),250);
}
updatePathGate=function(){
  if(!rtState)return;approvedPath=rtState.path_approved&&!rtFormTimer&&!rtFormError;
  launchButton.classList.toggle('uc-path-blocked',!approvedPath);launchButton.setAttribute('aria-disabled',String(!approvedPath));
  launchButton.dataset.tooltip=approvedPath?'Создать настоящие PDF с текущими параметрами':'Проверьте папку для текущего заказа во вкладке «Путь»';
  rtText(pathGateNote,approvedPath?'Папка проверена для текущего заказа.':'Проверка места не выполнена или устарела. Перейдите в «Путь».');
};
async function rtPaintRows(){
  const token=++rtRenderToken;if(!rtState?.source){$('uc-rows').replaceChildren();$('uc-qr').replaceChildren();rtText($('uc-window'),'База не загружена');return;}
  const data=await rtAPI('rows?page='+Math.max(1,state.page));if(token!==rtRenderToken)return;
  state.page=data.page;window.ucodeRows={};const fragment=document.createDocumentFragment();
  for(const [number,value] of data.rows){window.ucodeRows[number]=value;
    const tr=el('tr');tr.setAttribute('aria-selected',String(number===state.page));const index=el('td',fmt(number)),cell=el('td'),label=el('label'),radio=el('input'),text=el('span',value);
    radio.type='radio';radio.name='uc-selected-row';radio.checked=number===state.page;radio.setAttribute('aria-label','Выбрать строку '+number);radio.dataset.tooltip=radio.getAttribute('aria-label');
    radio.onchange=()=>{state.page=number;render();};label.append(radio,text);cell.append(label);tr.append(index,cell);fragment.append(tr);
  }
  $('uc-rows').replaceChildren(fragment);jump.value=fmt(state.page);$('uc-page').value=state.page;
  of.textContent='/ '+fmt(state.count);$('uc-pages').textContent=of.textContent;first.disabled=back.disabled=state.page===1;last.disabled=forward.disabled=state.page>=state.count;
  rtText($('uc-window'),data.rows.length?'Строки '+fmt(data.rows[0][0])+'–'+fmt(data.rows.at(-1)[0])+' из '+fmt(state.count)+' · UTF-8 · 12 цифр':'База пуста');
  rtText($('uc-value'),window.ucodeRows[state.page]||'');
  const image=el('img');image.alt='QR Code · '+(window.ucodeRows[state.page]||'');image.src=rtBase+'api/preview?page='+state.page+'&revision='+rtState.revision;
  image.style.cssText='width:100%;height:100%;display:block';$('uc-qr').replaceChildren(image);
  if(!runActive){const selected=$('uc-rows').querySelector('tr[aria-selected=true]');if(selected)selected.scrollIntoView({block:'nearest'});}
  applyAppearance();fitPreview();applyBackground();rtScheduleFit();
}
render=function(){return rtPaintRows().then(()=>refreshFooter()).catch(rtError);};
find=function(){
  clearTimeout(searchDelay);const token=++searchToken,q=search.value.trim();hits.replaceChildren();searchNote.textContent='';if(!q)return;
  searchDelay=setTimeout(async()=>{try{const data=await rtAPI('search?q='+encodeURIComponent(q));if(token!==searchToken)return;
    hits.replaceChildren();data.rows.forEach(([number,value])=>rtButton(hits,value+' · строка '+fmt(number),()=>{go(number);hits.replaceChildren();}));
    searchNote.textContent=data.rows.length?'Первые '+data.rows.length+' совпадения':'Совпадений нет';
  }catch(error){if(token===searchToken)rtError(error);}},120);
};
// Replace the earlier listener's function object with a capturing handler.
search.addEventListener('input',event=>{event.stopImmediatePropagation();find();},true);
tableBox.addEventListener('wheel',event=>{
  if(!rtState?.source||runActive)return;
  const atEnd=tableBox.scrollTop+tableBox.clientHeight>=tableBox.scrollHeight-4,atStart=tableBox.scrollTop<2;
  if(event.deltaY>0&&atEnd&&state.page+30<state.count){event.preventDefault();go(Math.min(state.count,state.page+30));}
  else if(event.deltaY<0&&atStart&&state.page>1){event.preventDefault();go(Math.max(1,state.page-30));}
},{passive:false});
function rtLock(active){
  if(active===runActive)return;
  runActive=active;
  if(active){root.querySelectorAll('button,input,select,textarea,summary').forEach(control=>{
      if(control===forceStop||stopDialog.contains(control))return;disabledSnapshot.set(control,control.disabled);control.disabled=true;
    });clearTimeout(searchDelay);searchToken++;root.classList.add('uc-is-running');forceStop.hidden=false;forceStop.disabled=false;launchButton.setAttribute('aria-pressed','true');launchButton.textContent='Выполнение…';closeMenu();}
  else{restoreInteraction();if(stopDialog.open)stopDialog.close();clearInterval(countdownInterval);rtNonce=null;}
}
startRun=async function(){
  if(runActive||rtLoading)return;
  try{await rtFlushForm();rtFormTimer=null;updatePathGate();if(!approvedPath){activateTab(5);rtText($('uc-status'),'Проверьте папку для текущего заказа.');return;}
    await rtAction('generate');
  }catch(error){rtError(error);}
};
requestStop=async function(){
  if(!runActive||stopDialog.open)return;
  try{const answer=await rtAPI('stop-request',{});rtNonce=answer.nonce;let seconds=answer.delay;
    stopYes.disabled=stopNo.disabled=true;countdownText.textContent='Подтверждение через '+seconds+' секунды';stopDialog.showModal();
    clearInterval(countdownInterval);countdownInterval=setInterval(()=>{seconds--;countdownText.textContent=seconds>0?'Подтверждение через '+seconds+' сек':'Остановить или продолжить?';
      if(seconds<=0){clearInterval(countdownInterval);stopYes.disabled=stopNo.disabled=false;stopNo.focus();}},1000);
  }catch(error){rtError(error);}
};
forceStop.onclick=requestStop;stopYes.onclick=async()=>{try{await rtAPI('stop',{nonce:rtNonce});stopDialog.close();rtText($('uc-status'),'Остановка собственного процесса…');}catch(error){rtError(error);}};
finishRun=function(){rtLock(false);};
function rtApplyState(data){
  const oldSource=rtSourceDigest,wasBusy=runActive;rtState=data;rtSourceDigest=data.source?.digest||'';
  state.count=data.source?.count||0;state.start=data.source?.first||'500000000000';state.page=Math.max(1,Math.min(state.count||1,state.page));
  rtText($('uc-filename'),data.source?data.source.name:'Откройте TXT или создайте базу');
  baseFileInfo.replaceChildren(el('p',data.source?.name||'Файл не выбран'),el('p',data.source?fmt(data.source.count)+' строк · UTF-8 · 12 цифр':'Одна строка — один код'),el('p','Первый: '+(data.source?.first||'—')),el('p','Последний: '+(data.source?.last||'—')));
  rtLock(data.busy);refreshFooter();updatePathGate();
  if(oldSource!==rtSourceDigest){state.page=1;render();if(data.source)activateTab(1);}
  if(wasBusy&&!data.busy){rtHydrate(data);render();if(currentView.index===6)showTest(selectedTest);}
}
refreshFooter=function(){
  if(!rtState)return;
  const s=rtState,p=s.progress,r=s.result,f=s.form,total=s.plan?.total_codes||s.source?.count||0;
  rtText($('uc-status'),rtFormError||s.status);const percent=r&&['COMPLETE','UNVERIFIED','LIMITED'].includes(r.status)?100:p?.percent||0;
  const width=Math.max(0,Math.min(100,percent))+'%';if($('uc-bar').style.width!==width)$('uc-bar').style.width=width;
  rtText($('uc-data-count'),fmt(s.source?.count||0)+' строк · 12 символов');rtText($('uc-done'),p?fmt(p.done)+' / '+fmt(p.total)+' · '+percent.toFixed(1)+'%':'0 / '+fmt(total)+' · 0%');
  const wall=r?.seconds?.launcher_wall||r?.seconds?.total_including_qa||r?.elapsed_seconds||s.elapsed;
  rtText($('uc-elapsed'),'Прошло: '+rtClock(wall));
  const unit=p?.unit||'кодов';
  rtText($('uc-speed'),r?.kind==='txt-batch-pdf'&&r.count&&wall?'Средняя: '+(r.count/wall).toFixed(1)+' кодов/сек':r&&r.kind!=='txt-batch-pdf'?'Скорость каждого варианта — в отчёте':p?'Сейчас: '+Number(p.speed||0).toFixed(1)+' · средняя: '+Number(p.average_speed??p.speed??0).toFixed(1)+' '+unit+'/сек':'Сейчас / средняя: —');
  const load=r?.runtime_statistics?.cpu_telemetry?.phases?.['Вся операция']?.selected_cpu_load_pct||p?.live_resources?.cpu_load_pct;
  const memory=r?.runtime_statistics||p?.live_resources;
  const metrics=root.querySelectorAll('.uc-telemetry>div');
  rtText(metrics[6]?.querySelector('strong'),load&&load.sampled_seconds>0?load.mean.toFixed(1)+'% / '+load.max.toFixed(1)+'% · min '+load.min.toFixed(1)+'%':'— / — · нет достаточных замеров');
  rtText(metrics[7]?.querySelector('strong'),memory?rtBytes(memory.current_tree_rss_bytes)+' / '+rtBytes(memory.peak_tree_rss_bytes):'— / — · не измерялась');
  rtText($('uc-resource-cpu'),f.execution_backend==='thread'?'QR: потоки Python (GIL) · PDF: 1 процесс':'QR: '+(p?.execution?.confirmed_processes??(f.execution_backend==='serial'?1:f.workers))+' процессов · PDF: 1');
  const seconds=r?.seconds;rtText(metrics[10]?.querySelector('strong'),seconds?[seconds.code_encoding,Number(seconds.write_multipage||0)+Number(seconds.write_singles||0),seconds.quality_checks].map(v=>typeof v==='number'?v.toFixed(3)+' с':'—').join(' / '):'— / — / —');
  const estimate=s.estimate;rtText(metrics[4]?.querySelector('strong'),estimate?'PDF ≈ '+rtBytes(estimate.pdf_bytes)+' · время: нужна калибровка':'Вес / время: нужна калибровка');
  rtText(metrics[4]?.querySelector('span'),'Прогноз · оценка');
  rtText($('uc-output-info'),r?.data?.case_count!=null?'Серия: '+fmt(r.data.case_count)+' вариантов · подробности в отчёте':r?.files?fmt(r.files)+' PDF · '+(r.pages==null?'страницы: см. отчёт':fmt(r.pages)+' страниц')+' · '+rtBytes(r.bytes):'План: '+(f.mode==='multipage'?'1 PDF':f.mode==='singles'?fmt(total)+' PDF':'1 общий + '+fmt(total)+' отдельных PDF')+' · '+fmt(total*(f.mode==='both'?2:1))+' страниц');
  rtText($('uc-quality-info'),r?r.status+' · '+(r.status==='UNVERIFIED'?'качество не проверялось':'подробности в отчёте'):f.qa_mode==='deferred'?'Без проверки':'После создания: '+(f.qa_mode==='full'?'полная QA':'структура PDF'));
  rtText($('uc-order-info'),'QR Code · '+Number(f.print.module_mm*(21+2*f.print.quiet_modules)).toFixed(2)+' мм · CMYK '+f.print.ink.join(' / ')+' · статистика: '+(f.telemetry==='cpu'?'подробная':'минимальная'));
  $('uc-results').hidden=!r||!r.data;
  if(estimate){sampleBytes.value=(estimate.sample_page_bytes/1024).toFixed(2);tempBytes.value=(estimate.temporary_bytes/1024**2).toFixed(2);availableBytes.value=(estimate.free_bytes/1024**3).toFixed(2);
    rtText(spaceResult,'Нужно с запасом: '+(estimate.required_bytes/1024**3).toFixed(2)+' ГиБ · '+(s.path_approved?'проверено для текущего заказа':'проверка устарела'));
    rtText(diskStatus,'Свободно: '+(estimate.free_bytes/1024**3).toFixed(2)+' ГиБ · запись '+(estimate.probe?.bytes||32768)+' байт, flush + fsync');
  }
  const cfg=f.print;rtText($('uc-preview-caption'),(cfg.module_mm*(21+2*cfg.quiet_modules)).toFixed(2)+' × '+(cfg.module_mm*(21+2*cfg.quiet_modules)).toFixed(2)+' мм · '+(cfg.ink.join(',')==='0,0,0,100'?'K100 · одна чёрная краска':'CMYK '+cfg.ink.join(' / '))+' · поле '+cfg.quiet_modules+' модуля');
  const ramButton=$('uc-ram').nextElementSibling,ramLabels=['ОЗУ: АВТО','ОЗУ: МАКС. С РЕЗЕРВОМ','ОЗУ: 50%','ОЗУ: 80%'];
  if(ramButton?.tagName==='BUTTON'){const index=$('uc-ram').selectedIndex;ramButton.textContent=ramLabels[index];ramButton.setAttribute('aria-label',ramLabels[index]+'. Нажатие: '+ramLabels[(index+1)%ramLabels.length]);ramButton.dataset.tooltip=ramButton.getAttribute('aria-label');}
};
summary=function(){refreshFooter();};
persist=function(){if(!rtState||rtHydrating)return;clearTimeout(rtPollTimer);rtPollTimer=setTimeout(()=>rtAPI('ui',{theme:state.theme,rowFont:state.rowFont,allowSelect:state.allowSelect===true,statisticsOpen:statsExpanded}).catch(rtError),150);};
function rtNumbers(parent,label,value,onchange,integer=true){
  const wrap=el('label',label),input=el('input');input.type='text';input.inputMode=integer?'numeric':'decimal';input.value=Array.isArray(value)?value.join(', '):String(value);input.setAttribute('aria-label',label);wrap.append(input);parent.append(wrap);
  input.oninput=()=>onchange(input.value);if(!Array.isArray(value))numericInputs.add(input);return input;
}
function rtCycle(parent,label,values,current,onchange){
  const button=el('button');button.type='button';let selected=current;
  const paint=()=>{button.textContent=label+': '+(valueNames[selected]||String(selected));button.dataset.tooltip='Нажатие переключает значение';};
  button.onclick=()=>{selected=values[(values.indexOf(selected)+1)%values.length];onchange(selected);paint();};paint();parent.append(button);return button;
}
function rtPrintConfig(parent,cfg){
  const details=el('details'),heading=el('summary','PDF этого теста · независимо от рабочего заказа'),grid=el('div',null,'uc-form-grid');details.append(heading,grid);parent.append(details);
  const p=Object.assign({module_mm:.5,quiet_modules:4,ink:[0,0,0,100],pdf_profile:'standard',background_mode:'white',background_ink:[0,0,0,0]},cfg.print_settings||{});cfg.print_settings=p;
  rtNumbers(grid,'Модуль, мм',p.module_mm,v=>p.module_mm=rtNumber(v),false);rtNumbers(grid,'Поле, модулей',p.quiet_modules,v=>p.quiet_modules=rtNumber(v));
  ['C','M','Y','K'].forEach((name,i)=>rtNumbers(grid,'Код '+name+', %',p.ink[i],v=>p.ink[i]=rtNumber(v),false));
  rtCycle(grid,'Профиль PDF',['standard','compact'],p.pdf_profile,v=>p.pdf_profile=v);rtCycle(grid,'Фон',['white','color','transparent'],p.background_mode,v=>p.background_mode=v);
  ['C','M','Y','K'].forEach((name,i)=>rtNumbers(grid,'Подложка '+name+', %',p.background_ink[i],v=>p.background_ink[i]=rtNumber(v),false));
}
renderConfig=function(name){
  const cfg=rtConfigs[name];if(!cfg){testBody.append(el('p','Загрузка параметров…'));return;}
  const grid=el('div',null,'uc-form-grid');testBody.append(grid);
  for(const [key,value] of Object.entries(cfg)){
    const wrap=el('div',null,'uc-test-field');grid.append(wrap);const label=fieldNames[key]||key;wrap.append(el('span',label));
    if(key==='print_settings'){rtPrintConfig(wrap,cfg);continue;}
    if(Array.isArray(value)){
      let choices=choiceSets[key];
      if(key==='cpu_counts')choices=[...new Set(['1','2','4','6','8','12',String(rtState.hardware.cpu.available_physical||1),'all-2','all',...value])];
      if(key==='allocations'){
        choices=[...value];for(const [unit,total,reserve] of [['physical',rtState.hardware.cpu.available_physical,2],['logical',rtState.hardware.cpu.available_logical,4]])if(total){choices.push(unit+':'+total+':0');if(total>reserve)choices.push(unit+':'+(total-reserve)+':'+reserve);}choices=[...new Set(choices)];
      }
      if(choices){const chips=el('div',null,'uc-test-chips');wrap.append(chips);
        choices.forEach(option=>{const button=el('button',valueNames[option]||String(option));button.type='button';button.setAttribute('aria-pressed',String(cfg[key].includes(option)));
          button.onclick=()=>{cfg[key]=cfg[key].includes(option)?cfg[key].filter(v=>v!==option):[...cfg[key],option];button.setAttribute('aria-pressed',String(cfg[key].includes(option)));custom.value=cfg[key].join(', ');};chips.append(button);});
      }
      const numeric=value.length&&typeof value[0]==='number';const custom=rtNumbers(wrap,'Свой список',value,v=>{cfg[key]=v.split(',').map(x=>x.trim()).filter(Boolean).map(x=>numeric?rtNumber(x):x);});
      custom.dataset.tooltip='Несколько значений через запятую. Кнопки не ограничивают свой список.';
    }else if(typeof value==='number')rtNumbers(wrap,'Значение',value,v=>cfg[key]=rtNumber(v));
    else{
      const options=typeof value==='boolean'?[true,false]:key==='qa_mode'?['full','vector','deferred']:key==='ram_mode'?['auto','max','50%','80%']:key==='output_mode'?['multipage','singles','both']:key==='search_mode'?['staged','full']:key==='telemetry_mode'?['cpu','off']:['on','off'];
      rtCycle(wrap,'Режим',options,value,v=>cfg[key]=v);
    }
  }
  const note=el('p','Каждый выбранный вариант выполняется указанное число раз. Прогревы не входят в измеренные повторы.','uc-small');testBody.append(note);
  rtButton(testBody,'План серии',async()=>{const p=await rtAPI('test-plan',{name,config:cfg});note.textContent=JSON.stringify(p.plan,null,2);},'Рассчитать реальное количество вариантов без запуска PDF');
  rtButton(testBody,'Запустить тест',async()=>{await rtAPI('test-plan',{name,config:cfg});await rtAction('test-start',{name,config:cfg});});
  rtButton(testBody,'В консоль →',async()=>{const p=await rtAPI('test-plan',{name,config:cfg});rtConsoleText=p.command;showTest('Консоль');});
};
let rtConsoleText='test lab --codes 200 --cpu 1,all --repeats 1 --backend process --pdf compact --qa off --metrics cpu --xy on';
function rtConsole(){
  const input=el('textarea');input.value=rtConsoleText;input.setAttribute('aria-label','Команды тестов');input.oninput=()=>rtConsoleText=input.value;testBody.append(input);
  const note=el('pre');note.style.whiteSpace='pre-wrap';note.className='uc-small';
  const actions=el('div',null,'uc-row');testBody.append(actions,note);
  rtButton(actions,'Проверить',async()=>note.textContent=JSON.stringify(await rtAPI('console-plan',{text:input.value}),null,2));
  rtButton(actions,'Показать кнопками',async()=>{const p=await rtAPI('console-plan',{text:input.value});if(p.commands.length!==1)throw Error('Показать кнопками можно одну команду; серия сохраняется в консоли');
    const c=p.commands[0],names={lab:['LabConfig','CPU / RAM'],pipeline:['PipelineConfig','Конвейер'],search:['SearchConfig','Подбор ПК']};
    if(!names[c.kind]){rtScientificOptions=c.config;showTest('Научный');return;}rtConfigs[names[c.kind][0]]=c.config;showTest(names[c.kind][1]);});
  rtButton(actions,'Вставить',async()=>{input.value=rtConsoleText=await navigator.clipboard.readText();});rtButton(actions,'Очистить',()=>input.value=rtConsoleText='');
  rtButton(actions,'Загрузить команды',async()=>{const data=await rtAPI('console-load',{});if(data.text!==null)input.value=rtConsoleText=data.text;});
  rtButton(actions,'Сохранить команды',()=>rtAPI('console-save',{text:input.value}));
  rtButton(actions,'Запустить команды',()=>rtAction('test-start',{name:'console',config:{text:input.value}}));
  rtButton(actions,'Справка команд',async()=>{const help=await rtAPI('commands-help');note.textContent=help.text;});
  input.addEventListener('keydown',event=>{if(event.ctrlKey&&event.key==='Enter'){event.preventDefault();rtAction('test-start',{name:'console',config:{text:input.value}}).catch(rtError);}});
}
let rtCommandHelp='Полный справочник команд находится в проекте: docs/TEST_COMMANDS.md';
async function rtArchive(){
  const controls=el('div',null,'uc-row');testBody.append(controls);let selected=null;
  rtButton(controls,'Обновить',()=>showTest('Архив'));rtButton(controls,'Добавить старые тесты',()=>rtAction('dialog',{kind:'import'}));
  rtButton(controls,'Папка архива',()=>rtAPI('archive-action',{action:'folder'}));rtButton(controls,'Все в браузере',()=>rtAPI('archive-action',{action:'index'}));
  const filter=el('input');filter.placeholder='Поиск по архиву';controls.append(filter);const box=el('div',null,'uc-tablebox');box.style.height='auto';const table=el('table');box.append(table);testBody.append(box);
  const rows=await rtAPI('archive');if(selectedTest!=='Архив')return;
  const draw=()=>{const filtered=rows.filter(r=>JSON.stringify(r).toLowerCase().includes(filter.value.toLowerCase())),size=8;rtArchivePage=Math.max(0,Math.min(Math.ceil(filtered.length/size)-1,rtArchivePage));
    table.replaceChildren();const head=el('tr');['UTC','Вид','CPU','Кодов','Статус'].forEach(t=>head.append(el('th',t)));table.append(head);
    filtered.slice(rtArchivePage*size,rtArchivePage*size+size).forEach(row=>{const tr=el('tr');[row.created,row.kind_title||row.kind,row.cpu,row.counts,row.status_title||row.status].forEach(v=>tr.append(el('td',v)));tr.tabIndex=0;tr.onclick=()=>{selected=row.id;table.querySelectorAll('tr').forEach(r=>r.setAttribute('aria-selected',String(r===tr)));};tr.onkeydown=e=>{if(e.key==='Enter')tr.click();};table.append(tr);});};
  filter.oninput=()=>{rtArchivePage=0;draw();};draw();const nav=el('div',null,'uc-row');testBody.append(nav);
  rtButton(nav,'‹',()=>{rtArchivePage--;draw();});rtButton(nav,'›',()=>{rtArchivePage++;draw();});
  [['Открыть отчёт','report'],['Открыть папку','entry-folder'],['Графики','graph'],['Графики из JSON','graph-json']].forEach(([text,action])=>rtButton(nav,text,()=>rtAPI('archive-action',{action,id:selected})));
}
async function rtHistory(){
  const controls=el('div',null,'uc-row');testBody.append(controls);let selected=null,selectedCase=null;
  rtButton(controls,'Мои тесты',async()=>{await rtAPI('history-own',{});showTest('История');});rtButton(controls,'Другая папка',()=>rtAction('dialog',{kind:'history'}));rtButton(controls,'Обновить',()=>showTest('История'));
  const filter=el('input');filter.placeholder='Поиск';controls.append(filter);let stateFilter='all';rtCycle(controls,'Показать',['all','good','bad'],stateFilter,v=>{stateFilter=v;draw();});
  const table=el('table'),details=el('pre');details.className='uc-small';details.style.whiteSpace='pre-wrap';testBody.append(table,details);
  const data=await rtAPI('history');if(selectedTest!=='История')return;
  function draw(){const rows=data.entries.filter(r=>JSON.stringify(r).toLowerCase().includes(filter.value.toLowerCase())&&(stateFilter==='all'||(stateFilter==='good')===['COMPLETE','PASS'].includes(r.status))),size=5;
    rtHistoryPage=Math.max(0,Math.min(Math.ceil(rows.length/size)-1,rtHistoryPage));table.replaceChildren();
    rows.slice(rtHistoryPage*size,rtHistoryPage*size+size).forEach(row=>{const tr=el('tr');[row.date,row.counts,row.status,row.note].forEach(v=>tr.append(el('td',v)));tr.onclick=()=>{selected=row.id;table.querySelectorAll('tr').forEach(r=>r.setAttribute('aria-selected',String(r===tr)));};table.append(tr);});}
  filter.oninput=draw;draw();const nav=el('div',null,'uc-row');testBody.append(nav);
  rtButton(nav,'‹',()=>{rtHistoryPage--;draw();});rtButton(nav,'›',()=>{rtHistoryPage++;draw();});
  rtButton(nav,'Замеры',async()=>{const run=await rtAPI('history-action',{action:'details',id:selected});details.replaceChildren();
    for(const item of run.results){rtButton(details,item.case.id+' · '+item.status+' · '+JSON.stringify(item.summary||{}),()=>{selectedCase=item.case.id;details.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.textContent.startsWith(selectedCase+' ·'))));});}});
  [['Отчёт в браузере','report'],['PDF','pdf'],['Папка','folder']].forEach(([text,action])=>rtButton(nav,text,()=>rtAPI('history-action',{action,id:selected,case:selectedCase})));
}
async function rtScientific(legacy=false){
  testBody.append(el('p','Историческая методика: QR V1-M · K100 · 0,5 мм · поле 4 модуля · 3 повтора. Следующий размер только после допуска.','uc-small'));
  let size=rtScientificOptions.size;const selected=new Set(rtScientificOptions.methods||[]);rtCycle(testBody,'Масштаб',[200,1000,10000,'all'],size,v=>{size=v;rtScientificOptions.size=v;});
  const engines=await rtAPI('engines');if(!['Научный','Объединение'].includes(selectedTest))return;
  const chips=el('div',null,'uc-test-chips');testBody.append(chips);
  engines.mergers.forEach(engine=>{const b=rtButton(chips,engine.name+(engine.available?'':' — SKIPPED'),()=>{selected.has(engine.name)?selected.delete(engine.name):selected.add(engine.name);rtScientificOptions.methods=[...selected];b.setAttribute('aria-pressed',String(selected.has(engine.name)));},engine.reason||engine.name);
    b.disabled=!engine.available;b.setAttribute('aria-pressed',String(selected.has(engine.name)));});
  testBody.append(el('p','Прямое создание PDF входит всегда. Кнопки выбирают дополнительные движки объединения.','uc-small'));
  rtButton(testBody,'Все доступные',()=>{rtScientificOptions.methods=engines.mergers.filter(e=>e.available).map(e=>e.name);showTest(selectedTest);});
  rtButton(testBody,'Снять все',()=>{rtScientificOptions.methods=[];showTest(selectedTest);});
  if(legacy){rtButton(testBody,'Создать 200 QR',()=>rtAction('test-start',{name:'legacy',config:{count:200,action:'create'}}));rtButton(testBody,'Запустить бенчмарк',()=>rtAction('test-start',{name:'legacy',config:{count:200,methods:[...selected]}}));rtButton(testBody,'Перейти к 1 000',()=>rtAction('test-start',{name:'legacy',config:{count:1000}}));rtButton(testBody,'Открыть результаты',()=>rtAPI('result',{action:'report'}));}
  else rtButton(testBody,'Научный тест',()=>rtAction('test-start',{name:'scientific',config:{size,methods:[...selected]}}));
}
showTest=function(name){
  selectedTest=name;testBody.replaceChildren();testNav.querySelectorAll('button').forEach(button=>{const active=button.textContent===name;button.setAttribute('aria-selected',String(active));button.setAttribute('aria-pressed',String(active));});
  const schema={'CPU / RAM':'LabConfig','Конвейер':'PipelineConfig','Подбор ПК':'SearchConfig'}[name];
  if(schema)renderConfig(schema);else if(name==='Консоль')rtConsole();else if(name==='Архив')rtArchive().catch(rtError);else if(name==='История')rtHistory().catch(rtError);else rtScientific(name==='Объединение').catch(rtError);
};
async function rtHelpInApp(){
  const data=await rtAPI('help'),target=otherPanel;target.replaceChildren(otherHeader);const nav=el('div',null,'uc-test-nav'),article=el('section');target.append(nav,article);
  data.topics.forEach(topic=>rtButton(nav,topic.title,()=>{article.replaceChildren(el('h3',topic.title),el('p',topic.short));topic.paragraphs.forEach(p=>article.append(el('p',p,'uc-small')));rtButton(article,'← Назад',rtOther);}));nav.firstElementChild?.click();
  rtButton(target,'Полная интерактивная справка в браузере',()=>rtAPI('help',{}));
}
function rtOther(){
  otherPanel.replaceChildren(otherHeader);const grid=el('div',null,'uc-form-grid');otherPanel.append(grid);
  [['Обновить сведения о CPU / RAM / диске',()=>rtAction('resources')],['Проверить запись 32 КиБ',()=>rtAction('probe')],['Проверить готовый PDF',()=>rtAction('audit')],
   ['Открыть PDF',()=>rtAPI('result',{action:'pdf'})],['Открыть папку результата',()=>rtAPI('result',{action:'folder'})],['Отчёт в браузере',()=>rtAPI('result',{action:'report'})],
   ['Справка · F1',rtHelpInApp],['Полная справка с графическими схемами',()=>rtAPI('help',{})],['Версии и доступность движков',async()=>{
     const versions=await rtAPI('engines'),pre=el('pre',JSON.stringify(versions,null,2),'uc-small');pre.style.whiteSpace='pre-wrap';otherPanel.append(pre);}],
   ['Восстановить настройки',async()=>{const data=await rtAPI('reset',{});rtApplyState(data);rtHydrate(data);render();}],
   ['Установка и прежний интерфейс',()=>{otherPanel.append(el('p','Setup-PDF.cmd — установка зависимостей в папку проекта. Start-uCode.cmd — новый дизайн. Start-uCode-Legacy.cmd — прежнее окно. Результаты и старые версии не удаляются.','uc-small'));}]
  ].forEach(([text,action])=>rtButton(grid,text,action));
  otherPanel.append(el('p','Русский интерфейс. Полный English и GPU пока в разработке. Внешний сервер статистики не подключён; все результаты сохраняются локально.','uc-small'));
}
// Wire existing controls; remove prototype wording while retaining their styling.
root.setAttribute('aria-label','uCode · генерация QR и PDF');root.querySelector('.uc-legal>span').textContent='© 2026 · uCode · Антон Магомедов / uBrand · 0.3.0';
if($('uc-ram').options.length>4)$('uc-ram').remove(4);
$('uc-gen-note').textContent='Настоящий TXT UTF-8 сохраняется на вашем компьютере.';checkFolder.textContent='Проверить папку';calcSpace.textContent='Пересчитать и проверить';
[sampleBytes,tempBytes,availableBytes].forEach(input=>{input.readOnly=true;input.placeholder='Измеряется при проверке папки';});
availableBytes.closest('label').firstChild.textContent='Свободно, ГиБ';
availableBytes.setAttribute('aria-label','Свободно, ГиБ');tempBytes.closest('label').firstChild.textContent='Оценка временных данных, МиБ';tempBytes.setAttribute('aria-label','Оценка временных данных, МиБ');
$('uc-qr').setAttribute('aria-label','QR выбранной строки');
async function rtCheckPath(){await rtFlushForm();rtFormTimer=null;await rtAction('preflight');}
checkFolder.onclick=()=>rtCheckPath().catch(rtError);calcSpace.onclick=checkFolder.onclick;chooseFolder.onclick=()=>rtAction('dialog',{kind:'folder'}).catch(rtError);
launchButton.dataset.tooltip='Создать настоящие PDF из текущей базы';
customCPU.addEventListener('input',event=>{event.stopImmediatePropagation();groupInput(customCPU);rtSelectCPU(String(rtNumber(customCPU.value)));},true);
workersControl.addEventListener('input',()=>{rtChoice='legacy';rtCPUButtons();rtQueueForm();});
affinityField.addEventListener('input',()=>{rtChoice='legacy';rtCPUButtons();rtQueueForm();});
root.addEventListener('input',event=>{if(event.target.closest('#uc-center-panel-2,#uc-center-panel-3')||event.target===pathInput)rtQueueForm();});
root.addEventListener('change',event=>{if(event.target.dataset.ucSetting==='cpu_unit')rtSelectCPU(rtChoice==='legacy'?'all':rtChoice);else if(event.target.closest('#uc-center-panel-2,#uc-center-panel-3')||event.target===duplicateButton){if(event.target===$('uc-method')&&$('uc-method').selectedIndex!==0)rtChoice='legacy';rtCPUButtons();rtQueueForm();}});
bgMode.addEventListener('click',rtQueueForm);resetSettings.onclick=async()=>{try{const data=await rtAPI('reset',{});rtApplyState(data);rtHydrate(data);render();}catch(e){rtError(e);}};
document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||!root.contains(button))return;
  const action=button.dataset.action;if(!['open','use','save','share'].includes(action))return;
  event.preventDefault();event.stopImmediatePropagation();if(runActive)return;
  if(action==='open')rtAction('dialog',{kind:'source'}).catch(()=>{});
  else if(action==='share'){rtText($('uc-status'),'Сервер не подключён. Открывается локальный текстовый архив без PDF и кодов.');rtAPI('archive-action',{action:'folder'}).catch(rtError);}
  else{const spec=calc();if(spec)rtAction('sequence',{...spec,save:action==='save'}).catch(()=>{});}
},true);
const rtQRButton=typesPanel.querySelector('.uc-type button');document.addEventListener('click',event=>{if(event.target.closest('button')===rtQRButton&&!runActive){event.preventDefault();event.stopImmediatePropagation();activateTab(4);}},true);
const rtResults=$('uc-results').querySelectorAll('button');['pdf','folder','report'].forEach((action,i)=>{rtResults[i].removeAttribute('data-action');rtResults[i].onclick=()=>rtAPI('result',{action}).catch(rtError);});
const rtMenuHelp=[...menu.querySelectorAll('button')].find(b=>b.textContent.trim()==='Справка');if(rtMenuHelp)rtMenuHelp.onclick=()=>{closeMenu();activateTab(7);rtHelpInApp().catch(rtError);};
const rtLanguage=[...menu.querySelectorAll('button')].find(b=>b.textContent.includes('Язык'));if(rtLanguage){rtLanguage.removeAttribute('data-action');rtLanguage.textContent='Язык: Русский';rtLanguage.onclick=()=>rtText($('uc-status'),'Полный English пока в разработке.');}
const rtCycleOriginal=duplicateButton.onclick;duplicateButton.onclick=()=>{rtCycleOriginal();rtQueueForm();};
statsToggle.addEventListener('click',persist);selectTextButton.addEventListener('click',persist);
document.addEventListener('keydown',event=>{if(event.key==='F1'&&!runActive){event.preventDefault();activateTab(7);rtHelpInApp().catch(rtError);}});
window.addEventListener('beforeunload',event=>{if(runActive){event.preventDefault();event.returnValue='Генерация продолжится в локальном процессе. Остановить её можно через СТОП.';}});
// Preserve the approved geometry at its design size. Only the central region
// yields height on shorter screens; header/command/footer positions stay stable.
let rtFitTimer=null;
function rtFitWindow(){
  rtFitTimer=null;const bounds=root.getBoundingClientRect(),current=parseFloat(root.style.getPropertyValue('--uc-stage-base'))||340;
  const next=Math.max(110,Math.min(340,current+innerHeight-bounds.height-16));
  if(Math.abs(current-next)>.5)root.style.setProperty('--uc-stage-base',next+'px');
  if(currentView.kind==='tab'&&currentView.index===1){const h=Math.max(95,stage.getBoundingClientRect().height-75);previewAnchor.style.height=h+'px';
    const size=Math.min(195,Math.max(70,Number(digits($('uc-side').value).replace(',','.'))/14.5*160),Math.max(70,h-22));
    const paper=root.querySelector('.uc-paper');paper.style.width=size+'px';paper.style.height=size+'px';}
}
function rtScheduleFit(){if(rtFitTimer===null)rtFitTimer=requestAnimationFrame(rtFitWindow);}
const rtPaintView=paintView;paintView=function(view){rtPaintView(view);rtScheduleFit();};
window.addEventListener('resize',rtScheduleFit);new ResizeObserver(rtScheduleFit).observe(footer);
async function rtPoll(){
  try{rtApplyState(await rtAPI('state'));}catch(error){rtText($('uc-status'),'Связь с локальным процессом прервана. Откройте Start-uCode.cmd для подключения.');}
  setTimeout(rtPoll,runActive?350:1000);
}
(async()=>{
  rtText($('uc-filename'),'Подключение к локальному процессу…');rtText($('uc-status'),'Загрузка uCode…');
  root.querySelectorAll('.uc-telemetry strong').forEach(node=>rtText(node,'—'));
  try{const data=await rtAPI('state');rtApplyState(data);rtHydrate(data);rtConfigs=await rtAPI('configs');showTest('CPU / RAM');rtOther();render();
    const image=el('img');image.src=rtBase+'api/preview?sample=1';image.alt='QR Code';image.style.cssText='height:100%;max-width:100%';$('uc-type-qr').replaceChildren(image);
    if(!data.source)activateTab(4);rtPoll();
  }catch(error){rtError(error);}
})();
