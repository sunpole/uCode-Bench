// Extension runs at the end of the approved renderer closure.
// Nothing in operator-approved.html is changed, preserving its SHA-256.
const ucUpPanel=el('div',null,'uc-update-center');
const ucUpHeading=el('div',null,'uc-section-title');
ucUpHeading.append(el('span','Обновление'));ucUpPanel.append(ucUpHeading);
const ucUpIntro=el('div',null,'uc-up-intro'),ucUpHeader=el('div');
ucUpHeader.append(el('h3','Центр обновлений'),el('p','Проверка версии не затрагивает PDF, TXT, настройки и результаты тестов.'));
const ucUpChannel=el('select',null,'uc-up-chip');
ucUpChannel.setAttribute('aria-label','Канал обновлений');
for(const [value,title] of [['stable','Stable · релизы'],['development','Development · main']]){
  const choice=el('option',title);choice.value=value;ucUpChannel.append(choice);
}
ucUpChannel.value='stable';
ucUpIntro.append(ucUpHeader,ucUpChannel);
ucUpPanel.append(ucUpIntro);
const ucUpTiles=el('div',null,'uc-up-tiles'),ucUpValues={};
for(const [key,label,placeholder,hint] of [
  ['installed','Установлено','—','Текущая версия программы'],
  ['latest','Версия GitHub','Не проверено','Опубликованные стабильные выпуски'],
  ['platform','Платформа','—','Пакет для вашей ОС']
]){
  const tile=el('section',null,'uc-up-tile');
  tile.append(el('div',label,'uc-up-label'));
  const value=el('div',placeholder,'uc-up-value');
  value.id='uc-up-'+key;ucUpValues[key]=value;
  tile.append(value,el('div',hint,'uc-up-sub'));ucUpTiles.append(tile);
}
ucUpPanel.append(ucUpTiles);
const ucUpBody=el('div',null,'uc-up-body'),ucUpLeft=el('section',null,'uc-up-card'),ucUpRight=el('section',null,'uc-up-card');
ucUpLeft.append(el('h4','Состояние обновления'));
const ucUpStatus=el('div','Проверка GitHub выполняется только после нажатия кнопки.','uc-up-status');
ucUpStatus.setAttribute('role','status');ucUpStatus.setAttribute('aria-live','polite');ucUpLeft.append(ucUpStatus);
const ucUpActions=el('div',null,'uc-up-actions');
const ucUpCheck=el('button','Проверить обновления','uc-main');
ucUpCheck.type='button';ucUpCheck.setAttribute('data-tooltip','Проверить последний стабильный выпуск через GitHub по вашему запросу.');
const ucUpOpen=el('button','Открыть выпуски GitHub');
ucUpOpen.type='button';ucUpOpen.setAttribute('data-tooltip','Открыть официальную страницу выпусков в браузере.');
const ucUpInstall=el('button','Установить обновление');
ucUpInstall.type='button';ucUpInstall.disabled=true;ucUpInstall.setAttribute('data-tooltip','Установить более новый стабильный релиз после проверки и явного подтверждения.');
ucUpActions.append(ucUpCheck,ucUpOpen,ucUpInstall);ucUpLeft.append(ucUpActions);
const ucUpPackage=el('div','Пакет: не проверен','uc-up-note');
const ucUpResult=el('div','Никаких скачиваний и изменений файлов.','uc-up-note');
ucUpLeft.append(ucUpPackage,ucUpResult);
ucUpRight.append(el('h4','Безопасность и порядок'));
for(const [number,text] of [
  ['1','Проверяем официальный стабильный GitHub Release, не ветку main.'],
  ['2','Перед установкой сверяем SHA-256 и запрашиваем согласие.'],
  ['3','uCode закрывается; его файлы обновляет отдельный uCode.Updater.exe.'],
  ['4','Пользовательские данные сохраняются, при неудаче нужен откат.']
]){
  const row=el('div',null,'uc-up-step');row.append(el('b',number),el('span',text));ucUpRight.append(row);
}
ucUpRight.append(el('p','Новая stable-версия устанавливается в отдельную папку после проверки SHA-256 и тестового запуска. Прежняя версия сохраняется для отката.','uc-up-note'));
ucUpBody.append(ucUpLeft,ucUpRight);ucUpPanel.append(ucUpBody);
addMainTab(ucUpPanel,'Обновление',8,'var(--uc-base-color)');
const ucUpTabOrder=[0,4,5,2,3,1,6,7,8];tabstrip.append(tabs[8]);
for(let p=0;p<ucUpTabOrder.length;p++){
  const i=ucUpTabOrder[p];
  tabs[i].onkeydown=event=>{
    if(event.key!=='ArrowLeft'&&event.key!=='ArrowRight')return;
    event.preventDefault();
    const next=ucUpTabOrder[(p+(event.key==='ArrowRight'?1:ucUpTabOrder.length-1))%ucUpTabOrder.length];
    activateTab(next);tabs[next].focus();
  };
}
const ucUpPaint=paintView;
paintView=function(view){
  ucUpPaint(view);
  if(view.kind==='tab'&&view.index===8)root.style.setProperty('--uc-hover','var(--uc-active)');
};
function ucUpSetStatus(text,state='idle'){ucUpStatus.textContent=text;ucUpStatus.dataset.state=state;}
const ucUpPlatform={'windows-x64':'Windows x64','linux-x64':'Linux x64','macos-arm64':'macOS ARM64'};
let ucUpCandidate=null,ucUpPollTimer=null;
function ucUpCanInstall(info){
  if(!info||info.status!=='UPDATE_AVAILABLE'||!info.package||
      info.platform!=='windows-x64'||!window.pywebview?.api?.finish_close)return false;
  if(ucUpChannel.value==='development')return info.channel==='development'&&
    typeof info.latest_commit==='string'&&/^[a-f0-9]{40}$/.test(info.latest_commit);
  return info.channel!=='development'&&typeof info.latest==='string';
}
ucUpChannel.onchange=()=>{
  ucUpCandidate=null;ucUpInstall.disabled=true;
  ucUpValues.latest.textContent='Не проверено';
  ucUpPackage.textContent='Пакет: не проверен';
  ucUpSetStatus('Выбран канал '+ucUpChannel.value+'. Нажмите «Проверить обновления».');
};
function ucUpStopPolling(){
  if(ucUpPollTimer!==null){clearInterval(ucUpPollTimer);ucUpPollTimer=null;}
}
async function ucUpWatchInstall(){
  try{
    const status=await rtAPI('updates-status',{});
    ucUpSetStatus(status.message,status.state==='FAILED'?'error':'idle');
    if(status.state==='RESTART_READY'){
      ucUpStopPolling();
      ucUpSetStatus('Новая версия готова. Закрываем старую программу и запускаем обновлённую.','success');
      if(window.pywebview?.api?.finish_close){await window.pywebview.api.finish_close();}
      else ucUpSetStatus('Закройте текущее окно uCode, чтобы завершить установку.','error');
    }else if(status.state==='FAILED'||status.state==='FINISHED'){
      ucUpStopPolling();ucUpCheck.disabled=false;
      if(status.state==='FAILED')ucUpResult.textContent='Прежняя версия сохранена. Причина записана в локальный журнал.';
    }
  }catch(error){
    ucUpStopPolling();ucUpCheck.disabled=false;
    ucUpSetStatus('Не удалось прочитать состояние установки: '+error.message,'error');
  }
}
ucUpInstall.onclick=async()=>{
  if(ucUpInstall.disabled||!ucUpCanInstall(ucUpCandidate))return;
  const dev=ucUpChannel.value==='development';
  const version=dev?'Development '+ucUpCandidate.latest_commit.slice(0,12):'v'+ucUpCandidate.latest;
  if(!window.confirm('Установить uCode '+version+'? После проверки программа закроется и запустится новая сборка. TXT, PDF и настройки сохраняются.'))return;
  ucUpInstall.disabled=true;ucUpCheck.disabled=true;
  ucUpSetStatus('Запуск независимого установщика…');
  try{
    await rtAPI(dev?'updates-install-dev':'updates-install',
      dev?{confirm:true,latest_commit:ucUpCandidate.latest_commit}:{confirm:true,latest:ucUpCandidate.latest});
    ucUpResult.textContent='Установка выполняется в отдельной папке. Прежняя версия не удаляется.';
    ucUpStopPolling();
    ucUpPollTimer=setInterval(()=>{ucUpWatchInstall();},900);
    await ucUpWatchInstall();
  }catch(error){
    ucUpSetStatus('Установка не запущена: '+error.message,'error');
    ucUpCheck.disabled=false;
    ucUpInstall.disabled=!ucUpCanInstall(ucUpCandidate);
  }
};
async function ucUpInitialize(){
  try{
    const info=await rtAPI('update-info');
    ucUpValues.installed.textContent='v'+info.installed;
    ucUpValues.platform.textContent=ucUpPlatform[info.platform]||'Не определена';
    ucUpChannel.value=info.channel==='development'?'development':'stable';
    if(info.channel==='development'&&info.build_commit){
      ucUpValues.installed.textContent='v'+info.installed+' · dev';
      ucUpResult.textContent='Тестовая сборка '+info.build_commit.slice(0,12)+'. Устанавливаются только более новые официальные стабильные релизы.';
    }
  }catch(error){ucUpSetStatus('Не удалось прочитать локальную версию: '+error.message,'error');}
}
ucUpCheck.onclick=async()=>{
  if(ucUpCheck.disabled)return;
  ucUpCheck.disabled=true;ucUpInstall.disabled=true;ucUpCandidate=null;ucUpCheck.textContent='Проверка…';
  ucUpSetStatus('Проверяем канал '+ucUpChannel.value+' через GitHub Releases…');
  ucUpPackage.textContent='Пакет: проверяется';
  try{
    const dev=ucUpChannel.value==='development';
    const info=await rtAPI(dev?'updates-check-dev':'updates-check',{});
    if(dev){
      ucUpValues.installed.textContent='Development';
      ucUpValues.latest.textContent=info.latest_commit?
        info.latest_commit.slice(0,12):'Нет опубликованных сборок';
    }else{
      ucUpValues.installed.textContent='v'+info.installed;
      ucUpValues.latest.textContent='v'+info.latest;
    }
    ucUpValues.platform.textContent=ucUpPlatform[info.platform]||'Не определена';
    const descriptions=dev?
      {CURRENT:'Установлена последняя Development-сборка.',UPDATE_AVAILABLE:'Новая проверенная Development-сборка доступна для установки.',NO_PUBLISHED_BUILD:'Пока нет проверенных Development-сборок.'}:
      {CURRENT:'Установлена актуальная стабильная версия.',UPDATE_AVAILABLE:'Есть новая стабильная версия. Можно подтвердить установку.',LOCAL_NEWER:'Эта локальная версия новее последнего стабильного выпуска.'};
    ucUpCandidate=info;ucUpInstall.disabled=!ucUpCanInstall(info);
    ucUpSetStatus(descriptions[info.status]||'Статус версии не определён.','success');
    ucUpPackage.textContent=info.package?'Доступен пакет: '+info.package.name+' · '+rtBytes(info.package.size_bytes):'Для этой платформы подходящий архив не найден.';
    ucUpResult.textContent='Проверка завершена · файлы, настройки и PDF не изменялись.';
  }catch(error){
    ucUpValues.latest.textContent='Нет данных';ucUpCandidate=null;ucUpInstall.disabled=true;
    ucUpSetStatus('Проверка не удалась: '+error.message,'error');
    ucUpPackage.textContent='Пакет не проверен. Сеть может быть недоступна.';
    ucUpResult.textContent='При ошибке установка не выполняется.';
  }finally{ucUpCheck.disabled=false;ucUpCheck.textContent='Проверить обновления';}
};
ucUpOpen.onclick=async()=>{
  try{await rtAPI('updates-open',{});ucUpResult.textContent='Открыта официальная страница GitHub Releases.';}
  catch(error){ucUpSetStatus(error.message,'error');}
};
ucUpInitialize();
