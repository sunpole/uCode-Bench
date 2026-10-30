// Extension runs at the end of the approved renderer closure.
// Nothing in operator-approved.html is changed, preserving its SHA-256.
const ucUpPanel=el('div',null,'uc-update-center');
const ucUpHeading=el('div',null,'uc-section-title');
ucUpHeading.append(el('span','Обновление'));ucUpPanel.append(ucUpHeading);
const ucUpIntro=el('div',null,'uc-up-intro'),ucUpHeader=el('div');
ucUpHeader.append(el('h3','Центр обновлений'),el('p','Проверка версии не затрагивает PDF, TXT, настройки и результаты тестов.'));
ucUpIntro.append(ucUpHeader,el('span','Канал: Стабильный','uc-up-chip'));
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
ucUpInstall.type='button';ucUpInstall.disabled=true;ucUpInstall.setAttribute('data-tooltip','Безопасный установщик с резервной копией и откатом разрабатывается отдельно.');
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
ucUpRight.append(el('p','Сейчас готова только проверка версии. Независимый установщик разрабатывается и ещё не устанавливает файлы.','uc-up-note'));
ucUpBody.append(ucUpLeft,ucUpRight);ucUpPanel.append(ucUpBody);
addMainTab(ucUpPanel,'Обновление',8,'var(--uc-active)');
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
async function ucUpInitialize(){
  try{
    const info=await rtAPI('update-info');
    ucUpValues.installed.textContent='v'+info.installed;
    ucUpValues.platform.textContent=ucUpPlatform[info.platform]||'Не определена';
  }catch(error){ucUpSetStatus('Не удалось прочитать локальную версию: '+error.message,'error');}
}
ucUpCheck.onclick=async()=>{
  if(ucUpCheck.disabled)return;
  ucUpCheck.disabled=true;ucUpCheck.textContent='Проверка…';
  ucUpSetStatus('Подключение к официальным GitHub Releases…');
  ucUpPackage.textContent='Пакет: проверяется';
  try{
    const info=await rtAPI('updates-check',{});
    ucUpValues.installed.textContent='v'+info.installed;
    ucUpValues.latest.textContent='v'+info.latest;
    ucUpValues.platform.textContent=ucUpPlatform[info.platform]||'Не определена';
    const descriptions={CURRENT:'Установлена актуальная стабильная версия.',UPDATE_AVAILABLE:'Есть новая стабильная версия. Установка пока выполняется вручную.',LOCAL_NEWER:'Эта локальная версия новее последнего стабильного выпуска.'};
    ucUpSetStatus(descriptions[info.status]||'Статус версии не определён.','success');
    ucUpPackage.textContent=info.package?'Доступен пакет: '+info.package.name+' · '+rtBytes(info.package.size_bytes):'Для этой платформы подходящий архив не найден.';
    ucUpResult.textContent='Проверка завершена · файлы, настройки и PDF не изменялись.';
  }catch(error){
    ucUpValues.latest.textContent='Нет данных';
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
