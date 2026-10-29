"""XY renderer embedded in the existing fixed report script, no dependencies."""

XY_FUNCTION = r'''
const xyChoice=el('label','Повтор и этап XY: ',null),xySelect=el('select',null,xyChoice);xyChoice.className='uc-xy-choice';xyChoice.hidden=true;canvas.before(xyChoice);
(model.timelines||[]).forEach((v,i)=>{const o=el('option',v.label,xySelect);o.value=String(i);});xySelect.addEventListener('change',draw);
function drawXY(){
 select.parentElement.hidden=true;xyChoice.hidden=false;root.querySelector('.uc-data').replaceChildren();
 root.querySelector('.uc-prev').disabled=true;root.querySelector('.uc-next').disabled=true;root.querySelector('.uc-page').textContent='';
 const v=(model.timelines||[])[Number(xySelect.value)];root.querySelector('.uc-save').disabled=!v;
 if(!v){msg.textContent='В этом запуске временной ряд не записывался. Для нового теста включите «XY: Записывать» или --xy on. Для старого отчёта кривую восстановить нельзя.';root.querySelector('.uc-scope').textContent='XY строится только по сохранённым временным наблюдениям, без расчётных промежуточных точек.';return;}
 const ps=v.points,rates=ps.filter(p=>Number.isFinite(p[2])),w=1120,h=500,left=90,right=1060,top=112,bottom=400,last=ps[ps.length-1],end=Math.max(last[0],.001),max=Math.max(1,...rates.map(p=>p[2]))*1.1;
 const x=t=>left+t/end*(right-left),y=rate=>bottom-rate/max*(bottom-top),svg=svgEl('svg',{viewBox:`0 0 ${w} ${h}`,role:'img','aria-label':'XY: время, количество, скорость'},canvas);
 svgEl('title',{},svg,v.label);svgEl('text',{x:left,y:22,fill:'#edf4fc','font-size':16},svg,v.counter_kind==='written_pages'?'Записанные страницы PDF':'Закодированные QR — ещё не готовые страницы PDF');
 svgEl('text',{x:left,y:49,fill:'#f6c763','font-size':14},svg,'Сверху: фактическое количество в отмеченный момент времени · цель '+fmt(v.target));
 for(let i=0;i<=4;i++){const n=max*i/4,py=y(n);svgEl('line',{x1:left,x2:right,y1:py,y2:py,stroke:'#344861','stroke-dasharray':'4 5'},svg);svgEl('text',{x:left-12,y:py+4,fill:'#b9cadf','font-size':12,'text-anchor':'end'},svg,fmt(n));}
 svgEl('text',{x:14,y:92,fill:'#b9cadf','font-size':13},svg,'кодов/с');
 // Both horizontal axes share time coordinates. Count ticks use actual observations only.
 let ticks=[];for(let i=0;i<=6;i++){const target=end*i/6;let p=ps.reduce((a,b)=>Math.abs(b[0]-target)<Math.abs(a[0]-target)?b:a);if(!ticks.includes(p))ticks.push(p);}
 ticks.sort((a,b)=>a[0]-b[0]);let previous=-1000;
 for(const p of ticks){const px=x(p[0]);if(px-previous<65)continue;previous=px;svgEl('line',{x1:px,x2:px,y1:top-12,y2:bottom+8,stroke:'#405b78','stroke-dasharray':'3 5'},svg);svgEl('text',{x:px,y:top-20,fill:'#f6c763','font-size':13,'text-anchor':'middle'},svg,fmt(p[1]));svgEl('text',{x:px,y:bottom+27,fill:'#b9cadf','font-size':12,'text-anchor':'middle'},svg,fmt(p[0]));}
 svgEl('line',{x1:left,x2:right,y1:bottom,y2:bottom,stroke:'#b9cadf'},svg);svgEl('line',{x1:left,x2:left,y1:top,y2:bottom,stroke:'#b9cadf'},svg);
 svgEl('text',{x:(left+right)/2,y:bottom+54,fill:'#b9cadf','font-size':14,'text-anchor':'middle'},svg,'Реальное прошедшее время наблюдения, секунд');
 if(rates.length){svgEl('polyline',{points:rates.map(p=>x(p[0])+','+y(p[2])).join(' '),fill:'none',stroke:'#59dfbc','stroke-width':2},svg);for(const p of rates){const c=svgEl('circle',{cx:x(p[0]),cy:y(p[2]),r:3,fill:'#59dfbc',tabindex:0},svg);svgEl('title',{},c,'Время '+fmt(p[0])+' с · готово '+fmt(p[1])+' · скорость '+fmt(p[2])+' кодов/с за наблюдавшийся интервал '+fmt(p[3])+' с');}}
 else msg.textContent='Сохранён только счётчик: для скорости нужны два наблюдения с разным временем. Нулевая скорость не выдумывается.';
 const s=v.stats;svgEl('text',{x:left,y:485,fill:'#edf4fc','font-size':14},svg,'Наблюдения: минимум '+fmt(s.min)+' · средняя по времени '+fmt(s.mean)+' · пик '+fmt(s.max)+' кодов/с');
 root.querySelector('.uc-scope').textContent=v.label+' · статус '+v.status+' · счётчик '+fmt(last[1])+' / '+fmt(v.target)+' ('+fmt(100*last[1]/v.target)+'% этапа).';
 if(v.status!=='COMPLETE'&&v.status!=='PASS')msg.textContent+=' Статус '+v.status+': график не подтверждает качество PDF. ';
 if(v.compactions)msg.textContent+='Длинный ряд сокращён до '+ps.length+' точек; min/средняя/max посчитаны по всем '+v.observations+' принятым наблюдениям. ';
 if(model.omitted_timelines)msg.textContent+='Часть рядов не отображена из-за лимита4096. ';
 const box=root.querySelector('.uc-data'),t=el('table',null,box),head=el('tr',null,t);['Время, с','Готово','Скорость, кодов/с','Интервал наблюдения, с'].forEach(k=>el('th',k,head));ps.forEach(p=>{const row=el('tr',null,t);p.forEach(n=>el('td',fmt(n),row));});
 el('p','Каждая точка — сохранённое наблюдение. Линия соединяет точки для чтения; между ними мгновенная скорость неизвестна. Две горизонтальные шкалы имеют общую координату времени: количество сверху не является независимой линейной шкалой. Счётчик записанных страниц не означает завершение закрытия PDF и QA.',canvas).className='uc-subtle';
}
'''
