const test=require('node:test');
const assert=require('node:assert/strict');
const {cpuSelection}=require('../ucode/assets/operator-controls.js');
const cpu={available_physical:14,available_logical:28};
test('core choices mean separate processes even after a serial/thread choice',()=>{
  for(const previous of ['serial','thread','process']){
    const state={execution_backend:previous,workers:1,...cpuSelection(cpu,'physical','all')};
    assert.equal(state.execution_backend,'process');assert.equal(state.workers,14);
  }
});
test('physical/SMT all-minus-two and custom counts use current hardware',()=>{
  assert.equal(cpuSelection(cpu,'physical','all-2').workers,12);
  assert.equal(cpuSelection(cpu,'logical','all-2').workers,26);
  assert.equal(cpuSelection(cpu,'logical','all').workers,28);
  assert.equal(cpuSelection(cpu,'physical','2').workers,2);
  assert.equal(cpuSelection({available_physical:6,available_logical:12},'physical','all').workers,6);
  assert.throws(()=>cpuSelection(cpu,'physical','28'));
  assert.throws(()=>cpuSelection(cpu,'logical','0'));
  assert.throws(()=>cpuSelection(cpu,'logical','1.5'));
});
