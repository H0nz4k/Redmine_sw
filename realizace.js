(() => {
  'use strict';
  const key = 'redcheck.realizace.draft.v1';
  const tasks = [
    {id:'scope', title:'Převzít zakázku a ověřit rozsah dodávky', owner:'honza', info:'Zařízení, množství, termín a odpovědnosti.'},
    {id:'site', title:'Prohlídka a domluva s IT', owner:'honza', info:'Umístění, kabeláž, napájení, přístup a termín montáže.'},
    {id:'equipment', title:'Připravit zařízení, čtečky a čipy', owner:'honza', info:'Ověřit počet, typ čipů a kompatibilitu čteček.', hardware:true},
    {id:'install', title:'Instalovat potřebný software', owner:'', info:'Zajistit přístup a nainstalovat součásti podle zakázky.', software:true},
    {id:'database', title:'Nastavit databázi a služby', owner:'', info:'Získat a zkontrolovat implementační tabulku.', software:true},
    {id:'data', title:'Připravit a naplnit data', owner:'', info:'Domluvit zdroj dat, potřebné údaje a čipy.', software:true},
    {id:'integration', title:'Prověřit návaznosti Dorsysu', owner:'honza', info:'Přístup, režim připojení a případná integrace.', dorsys:true},
    {id:'mount', title:'Namontovat a zapojit zařízení', owner:'honza', info:'Koordinovat termín a připravenost místa.', hardware:true},
    {id:'training', title:'Zaškolit obsluhu', owner:'', info:'Domluvit obsluhu a potřebný rozsah školení.', software:true},
    {id:'handover', title:'Ověřit funkčnost a předat zákazníkovi', owner:'honza', info:'Doporučená závěrečná kontrola před uzavřením.'}
  ];
  const $ = id => document.getElementById(id);
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (_) { saved = {}; }
  const state = {name:typeof saved.name==='string'?saved.name:'', parent:typeof saved.parent==='string'?saved.parent:'', equipment:Array.isArray(saved.equipment)?saved.equipment:[], choices:saved.choices && typeof saved.choices==='object'?saved.choices:{}, owners:saved.owners && typeof saved.owners==='object'?saved.owners:{}};
  $('real-name').value=state.name;
  $('real-parent').value=state.parent;
  const equipment=Array.from(document.querySelectorAll('.realization-equipment input'));
  equipment.forEach(input => {input.checked=state.equipment.includes(input.value);});
  function relevant(task) { return (!task.hardware || state.equipment.some(x=>['tt3511','tt3503','zolík','dorsys'].includes(x))) && (!task.software || state.equipment.includes('software')) && (!task.dorsys || state.equipment.includes('dorsys')); }
  function selected(task) {return state.choices[task.id] !== false;}
  function owner(task) {return typeof state.owners[task.id] === 'string' ? state.owners[task.id] : task.owner;}
  function persist() {try {localStorage.setItem(key,JSON.stringify(state)); $('real-save-status').textContent='Návrh uložen v tomto prohlížeči.';} catch (_) {$('real-save-status').textContent='Návrh se nepodařilo uložit v prohlížeči.';}}
  function updateOutput() {
    const active=tasks.filter(t=>relevant(t)&&selected(t));
    $('real-count').textContent=`Vybráno: ${active.length}`;
    const devices=equipment.filter(x=>x.checked).map(x=>x.parentElement.textContent.trim());
    const lines=[`Realizace: ${state.name.trim() || 'doplnit název'}`,state.parent.trim()?`Nadřazený úkol: #${state.parent.trim()}`:'',`Dodávka: ${devices.join(', ') || 'není vybrána'}`,'','Dílčí úkoly:',...active.map(t=>`- ${t.title} — ${owner(t).trim() || 'řešitele doplnit'}`)];
    $('real-output').value=lines.filter((line,i)=>line || i!==1).join('\n');
    const link=$('real-parent-link');
    let base=''; try {base=typeof data !== 'undefined' && data?.base_url || '';} catch (_) {}
    if (/^\d{1,12}$/.test(state.parent.trim()) && /^https?:\/\//i.test(base)) {link.href=base.replace(/\/$/,'')+'/issues/'+state.parent.trim();link.hidden=false;} else {link.hidden=true;link.removeAttribute('href');}
  }
  function render() {
    const list=$('real-tasks'); list.replaceChildren();
    tasks.filter(relevant).forEach(task=>{
      const row=document.createElement('div'); row.className='realization-task';
      const label=document.createElement('label'); label.className='realization-task-label';
      const check=document.createElement('input'); check.type='checkbox'; check.checked=selected(task); check.setAttribute('aria-label','Zahrnout: '+task.title);
      check.addEventListener('change',()=>{state.choices[task.id]=check.checked; updateOutput();persist();});
      const text=document.createElement('span'), title=document.createElement('strong'), info=document.createElement('small'); title.textContent=task.title;info.textContent=task.info;text.append(title,info);label.append(check,text);
      const assignee=document.createElement('label'); assignee.className='realization-owner'; assignee.textContent='Řešitel';
      const input=document.createElement('input'); input.value=owner(task);input.placeholder='Doplnit';input.maxLength=80;input.setAttribute('aria-label','Řešitel: '+task.title);input.addEventListener('input',()=>{state.owners[task.id]=input.value;updateOutput();persist();});assignee.append(input);row.append(label,assignee);list.append(row);
    });updateOutput();
  }
  for(const [id,field] of [['real-name','name'],['real-parent','parent']]) $(id).addEventListener('input',e=>{state[field]=e.target.value;updateOutput();persist();});
  equipment.forEach(input=>input.addEventListener('change',()=>{state.equipment=equipment.filter(x=>x.checked).map(x=>x.value);render();persist();}));
  $('real-select').addEventListener('click',()=>{$('real-output').focus();$('real-output').select();$('real-save-status').textContent='Text je vybraný; zkopíruj jej pomocí Ctrl+C.';});
  $('real-clear').addEventListener('click',()=>{if (!window.confirm('Zahodit rozpracovaný návrh a začít nový?')) return; state.name='';state.parent='';state.equipment=[];state.choices={};state.owners={};$('real-name').value='';$('real-parent').value='';equipment.forEach(input=>{input.checked=false;});render();persist();$('real-name').focus();});
  document.querySelector('[data-view="realizace"]').addEventListener('click',updateOutput);
  render();
})();
