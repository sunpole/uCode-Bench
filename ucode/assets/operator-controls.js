/* Pure UI decisions shared by the approved renderer and executable regression tests. */
(function(root){
  function cpuSelection(cpu,unit,choice){
    if(!['physical','logical'].includes(unit))throw Error('Выберите ядра или потоки SMT');
    const maximum=unit==='physical'?cpu.available_physical:cpu.available_logical;
    const text=String(choice),workers=text==='all'?maximum:text==='all-2'?maximum-2:Number(text);
    if(!Number.isInteger(maximum)||!Number.isInteger(workers)||workers<1||workers>maximum)throw Error('Доступно CPU: '+maximum+'. Выберите допустимое количество.');
    return {choice:text,workers,cpu_unit:unit,execution_backend:'process'};
  }
  const api={cpuSelection};
  root.ucodeOperatorControls=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window==='undefined'?globalThis:window);
