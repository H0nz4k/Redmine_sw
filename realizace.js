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
  let context=null, pending=null, busy=false, reviewPlan=null;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (_) { saved = {}; }
  const state = {name:typeof saved.name==='string'?saved.name:'', parent:typeof saved.parent==='string'?saved.parent:'', equipment:Array.isArray(saved.equipment)?saved.equipment:[], choices:saved.choices && typeof saved.choices==='object'?saved.choices:{}, owners:saved.owners && typeof saved.owners==='object'?saved.owners:{}};
  pending=saved.pending && typeof saved.pending==='object' ? saved.pending : null;
  $('real-name').value=state.name;
  $('real-parent').value=state.parent;
  const equipment=Array.from(document.querySelectorAll('.realization-equipment input'));
  equipment.forEach(input => {input.checked=state.equipment.includes(input.value);});
  function relevant(task) { return (!task.hardware || state.equipment.some(x=>['tt3511','tt3503','zolík','dorsys'].includes(x))) && (!task.software || state.equipment.includes('software')) && (!task.dorsys || state.equipment.includes('dorsys')); }
  function selected(task) {return state.choices[task.id] !== false;}
  function owner(task) {return typeof state.owners[task.id] === 'string' ? state.owners[task.id] : task.owner;}
  function persist() {try {localStorage.setItem(key,JSON.stringify({...state,pending})); $('real-save-status').textContent='Návrh uložen v tomto prohlížeči.';return true;} catch (_) {$('real-save-status').textContent='Návrh se nepodařilo uložit v prohlížeči.';return false;}}
  function member(task) { const val=owner(task).trim(); if(!context)return null; const matches=context.members.filter(m=>String(m.id)===val||m.name.toLocaleLowerCase('cs')===val.toLocaleLowerCase('cs')); return matches.length===1?matches[0]:null; }
  function updateOutput() {
    const active=tasks.filter(t=>relevant(t)&&selected(t));
    $('real-count').textContent=`Vybráno: ${active.length}`;
    const devices=equipment.filter(x=>x.checked).map(x=>x.parentElement.textContent.trim());
    const lines=[`Realizace: ${state.name.trim() || 'doplnit název'}`,state.parent.trim()?`Nadřazený úkol: #${state.parent.trim()}`:'',`Dodávka: ${devices.join(', ') || 'není vybrána'}`,'','Dílčí úkoly:',...active.map(t=>`- ${t.title} — ${member(t)?.name || owner(t).trim() || 'řešitele doplnit'}`)];
    $('real-output').value=lines.filter((line,i)=>line || i!==1).join('\n');
    $('real-create').disabled=busy || !!pending || !context || context.id !== Number(state.parent) || !active.length || active.some(t=>!member(t));
    $('real-check').hidden=!pending; $('real-clear').disabled=busy;
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
      let input;
      if(context){input=document.createElement('select');const blank=document.createElement('option');blank.value='';blank.textContent='Vybrat řešitele';input.append(blank);context.members.forEach(m=>{const option=document.createElement('option');option.value=String(m.id);option.textContent=m.name;input.append(option)});input.value=String(member(task)?.id||'');input.addEventListener('change',()=>{state.owners[task.id]=input.value;updateOutput();persist();});}
      else {input=document.createElement('input');input.value=owner(task);input.placeholder='Nejdřív načti realizaci';input.disabled=true;}
      input.setAttribute('aria-label','Řešitel: '+task.title);assignee.append(input);row.append(label,assignee);list.append(row);
    });updateOutput();
  }
  for(const [id,field] of [['real-name','name'],['real-parent','parent']]) $(id).addEventListener('input',e=>{state[field]=e.target.value;if(field==='parent'){context=null;$('real-existing').hidden=true;$('real-load-status').textContent='';render();}updateOutput();persist();});
  equipment.forEach(input=>input.addEventListener('change',()=>{state.equipment=equipment.filter(x=>x.checked).map(x=>x.value);render();persist();}));
  $('real-select').addEventListener('click',()=>{$('real-output').focus();$('real-output').select();$('real-save-status').textContent='Text je vybraný; zkopíruj jej pomocí Ctrl+C.';});
  $('real-clear').addEventListener('click',()=>{if (pending && !window.confirm('Tento návrh má odeslaný požadavek. Nejprve ověřte výsledek v Redmine. Opravdu odstranit záznam o tomto pokusu?')) return; if (!window.confirm('Zahodit rozpracovaný návrh a začít nový?')) return; pending=null;context=null;$('real-existing').hidden=true;$('real-result').textContent='';$('real-load-status').textContent=''; state.name='';state.parent='';state.equipment=[];state.choices={};state.owners={};$('real-name').value='';$('real-parent').value='';equipment.forEach(input=>{input.checked=false;});render();persist();$('real-name').focus();});
  function showResult(result) {
    const box=$('real-result');box.replaceChildren();
    const head=document.createElement('strong');head.textContent=result.state==='complete'?'Všechny úkoly byly ověřeny v Redmine.':'Založení není dokončeno. Neověřené a neodeslané úkoly zkontroluj v Redmine.';box.append(head);
    const ul=document.createElement('ul');(result.tasks||[]).forEach(task=>{const li=document.createElement('li');const status={created:'založeno',unknown:'výsledek neznámý',sending:'výsledek neznámý',rejected:'odmítnuto',pending:'neodesláno'}[task.state]||task.state;li.textContent=task.subject+' — '+status+(task.issue_id?' (#'+task.issue_id+')':'')+(task.error?' · '+task.error:'');ul.append(li)});box.append(ul);
    if(result.state==='complete'){pending=null;persist();context=null;render();$('real-load-status').textContent='Před dalším založením načti realizaci znovu.';}
    updateOutput();
  }
  $('real-load').addEventListener('click',async()=>{
    if(pending){$('real-load-status').textContent='Nejdřív ověř stav předchozího založení.';return;}
    if(!/^[1-9][0-9]{0,11}$/.test(state.parent.trim())){$('real-load-status').textContent='Zadej číslo nadřazené realizace.';return;}
    const parent=state.parent.trim();$('real-load').disabled=true;$('real-load-status').textContent='Načítám realizaci a členy projektu…';
    try{const response=await apiFetch('/api/realization-prepare/'+parent),value=await response.json();if(!response.ok)throw Error(value.error||'Načtení se nezdařilo.');if(state.parent.trim()!==parent)return;context=value;$('real-load-status').textContent=`#${value.id} · ${value.subject} · ${value.members.length} řešitelů`;const existing=$('real-existing');existing.replaceChildren();const heading=document.createElement('strong');heading.textContent='Již existující dílčí úkoly';existing.append(heading);const ul=document.createElement('ul');value.children.forEach(c=>{const li=document.createElement('li');li.textContent='#'+c.id+' '+c.subject;ul.append(li)});if(!value.children.length){const li=document.createElement('li');li.textContent='Žádné';ul.append(li)}existing.append(ul);existing.hidden=false;render();}
    catch(e){context=null;render();$('real-load-status').textContent='Načtení se nezdařilo: '+e.message;}finally{$('real-load').disabled=false;}
  });
  $('real-create').addEventListener('click',()=>{
    const active=tasks.filter(t=>relevant(t)&&selected(t));if(!context||pending||!active.length||active.some(t=>!member(t)))return;
    const suffix=state.name.trim()||context.subject;const taskList=active.map(t=>({subject:t.title+' – '+suffix,description:t.info,assignee_id:member(t).id}));
    if(taskList.some(t=>t.subject.length>255)){$('real-result').textContent='Název úkolu je příliš dlouhý; zkrať název zakázky.';return;}
    reviewPlan={parent_id:context.id,token:context.token,tasks:taskList};
    $('real-confirm-parent').textContent=`Nadřazená realizace #${context.id}: ${context.subject}`;
    const list=$('real-confirm-list');list.replaceChildren();active.forEach((t,i)=>{const li=document.createElement('li');li.textContent=taskList[i].subject+' — '+member(t).name;list.append(li)});
    $('real-confirm').showModal();
  });
  $('real-cancel').addEventListener('click',()=>{$('real-confirm').close();reviewPlan=null;});
  $('real-confirm-send').addEventListener('click',async()=>{
    if(!reviewPlan||pending||busy)return;
    const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);const request_id=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
    pending={...reviewPlan,request_id};reviewPlan=null;$('real-confirm').close();if(!persist()){pending=null;$('real-result').textContent='Zápis nebyl odeslán: nelze uložit identifikátor pro ověření výsledku.';updateOutput();return;}busy=true;persist();updateOutput();$('real-result').textContent='Zakládám úkoly v Redmine…';
    try{const r=await apiFetch('/api/realization-create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pending)}),v=await r.json();if(!r.ok)throw Error(v.error||'Neznámý výsledek');showResult(v);}
    catch(e){$('real-result').textContent='Založení nelze potvrdit: '+e.message+'. Ověř stav a Redmine; neposílej znovu naslepo.';}
    finally{busy=false;updateOutput();}
  });
  $('real-check').addEventListener('click',async()=>{if(!pending)return;$('real-check').disabled=true;try{const r=await apiFetch('/api/realization-job/'+pending.request_id),v=await r.json();if(!r.ok)throw Error(v.error);showResult(v);}catch(e){$('real-result').textContent='Stav nelze ověřit: '+e.message+' Zkontroluj Redmine před novým pokusem.';}finally{$('real-check').disabled=false;}});
  document.querySelector('[data-view="realizace"]').addEventListener('click',updateOutput);
  render();
})();
