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
  let context=null, pending=null, busy=false, reviewPlan=null, selectedMatch=false, loadSeq=0;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (_) { saved = {}; }
  const state = {name:typeof saved.name==='string'?saved.name:'', parent:typeof saved.parent==='string'?saved.parent:'', equipment:Array.isArray(saved.equipment)?saved.equipment:[], choices:saved.choices && typeof saved.choices==='object'?saved.choices:{}, owners:saved.owners && typeof saved.owners==='object'?saved.owners:{}, notes:saved.notes && typeof saved.notes==='object'?saved.notes:{}};
  pending=saved.pending && typeof saved.pending==='object' ? saved.pending : null;
  selectedMatch=Boolean(state.name && state.parent);
  $('real-name').value=state.name;
  $('real-parent').value=state.parent;
  const equipment=Array.from(document.querySelectorAll('.realization-equipment input'));
  equipment.forEach(input => {input.checked=state.equipment.includes(input.value);});
  function relevant(task) { return (!task.hardware || state.equipment.some(x=>['tt3511','tt3503','zolík','dorsys'].includes(x))) && (!task.software || state.equipment.includes('software')) && (!task.dorsys || state.equipment.includes('dorsys')); }
  function selected(task) {return state.choices[task.id] !== false;}
  function owner(task) {return typeof state.owners[task.id] === 'string' ? state.owners[task.id] : task.owner;}
  function taskDescription(task) {const note=typeof state.notes[task.id]==='string'?state.notes[task.id].trim():'';return task.info+(note?'\n\n'+note:'');}
  function persist() {try {localStorage.setItem(key,JSON.stringify({...state,pending})); $('real-save-status').textContent='Návrh uložen v tomto prohlížeči.';return true;} catch (_) {$('real-save-status').textContent='Návrh se nepodařilo uložit v prohlížeči.';return false;}}
  function member(task) { const val=owner(task).trim(); if(!context)return null; const matches=context.members.filter(m=>String(m.id)===val||m.name.toLocaleLowerCase('cs')===val.toLocaleLowerCase('cs')); return matches.length===1?matches[0]:null; }
  function updateOutput() {
    const active=tasks.filter(t=>relevant(t)&&selected(t));
    const invalidDescription=active.some(t=>taskDescription(t).length>1000);
    $('real-count').textContent=`Vybráno: ${active.length}`+(invalidDescription?' · Příliš dlouhý popis úkolu':'');
    const devices=equipment.filter(x=>x.checked).map(x=>x.parentElement.textContent.trim());
    const lines=[`Realizace: ${state.name.trim() || 'doplnit název'}`,state.parent.trim()?`Nadřazený úkol: #${state.parent.trim()}`:'',`Dodávka: ${devices.join(', ') || 'není vybrána'}`,'','Dílčí úkoly:',...active.flatMap(t=>[`- ${t.title} — ${member(t)?.name || owner(t).trim() || 'řešitele doplnit'}`, ...((typeof state.notes[t.id]==='string' && state.notes[t.id].trim()) ? [`  Vlastní zpráva: ${state.notes[t.id].trim()}`] : [])])];
    $('real-output').value=lines.filter((line,i)=>line || i!==1).join('\n');
    $('real-create').disabled=busy || !!pending || !context || context.id !== Number(state.parent) || !active.length || invalidDescription || active.some(t=>!member(t));
    $('real-check').hidden=!pending; $('real-clear').disabled=busy;
    const link=$('real-parent-link');
    let base=''; try {base=typeof data !== 'undefined' && data?.base_url || '';} catch (_) {}
    if (/^\d{1,12}$/.test(state.parent.trim()) && /^https?:\/\//i.test(base)) {link.href=base.replace(/\/$/,'')+'/issues/'+state.parent.trim();link.hidden=false;} else {link.hidden=true;link.removeAttribute('href');}
  }
  function render() {
    const list=$('real-tasks'); list.replaceChildren();
    const bulk=$('real-bulk-owner'); bulk.replaceChildren();
    const empty=document.createElement('option'); empty.value=''; empty.textContent='Vyber řešitele';bulk.append(empty);
    (context?.members||[]).forEach(m=>{const option=document.createElement('option');option.value=String(m.id);option.textContent=m.name;bulk.append(option);});
    bulk.disabled=!context||busy;$('real-bulk-apply').disabled=true;
    $('real-member-hint').textContent=context?(context.members_warning || (context.members.length===1?'Redmine vrací jen jednoho člena projektu. Další řešitelé musí mít oprávnění v projektu Realizace.':'Dostupní řešitelé podle členství v projektu Realizace.')):'Po načtení realizace se zobrazí dostupní řešitelé.';
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
      input.setAttribute('aria-label','Řešitel: '+task.title);assignee.append(input);
      const noteLabel=document.createElement('label');noteLabel.className='realization-description';noteLabel.textContent='Vlastní zpráva do popisu úkolu (nepovinné)';
      const note=document.createElement('textarea');note.rows=2;note.maxLength=800;note.placeholder='Doplň pokyny nebo text pro tento úkol…';
      note.value=typeof state.notes[task.id]==='string'?state.notes[task.id]:'';
      note.setAttribute('aria-label','Vlastní zpráva: '+task.title);
      note.addEventListener('input',()=>{state.notes[task.id]=note.value;updateOutput();persist();});
      noteLabel.append(note);row.append(label,assignee,noteLabel);list.append(row);
    });updateOutput();
  }
  for(const [id,field] of [['real-name','name'],['real-parent','parent']]) $(id).addEventListener('input',e=>{
    if(context||selectedMatch){if(field==='name'){state.parent='';$('real-parent').value='';}else{state.name='';$('real-name').value='';}}
    state[field]=e.target.value;loadSeq++;selectedMatch=false;context=null;$('real-existing').hidden=true;$('real-load-status').textContent='';render();updateOutput();persist();
  });
  let searchSeq=0,searchTimer=null;
  function hideSuggestions(){searchSeq++;clearTimeout(searchTimer);for(const id of ['real-name','real-parent']){const field=$(id);field.setAttribute('aria-expanded','false');field.removeAttribute('aria-activedescendant');$(id+'-results').hidden=true;} $('real-search-status').textContent='';}
  function suggest(field) {
    const value=field.value.trim();hideSuggestions();if(pending||busy)return;
    if(value.replace(/^#/, '').length<2){if(value)$('real-search-status').textContent='Pro hledání zadej alespoň dva znaky.';return;}
    const sequence=searchSeq,results=$(field.id+'-results');$('real-search-status').textContent='Hledám otevřené realizace…';
    searchTimer=setTimeout(async()=>{
      try{
        const response=await apiFetch('/api/realization-search?q='+encodeURIComponent(value));const result=await response.json();if(!response.ok)throw Error(result.error||'Hledání se nezdařilo.');
        if(sequence!==searchSeq||field.value.trim()!==value||document.activeElement!==field)return;
        results.replaceChildren();const rows=Array.isArray(result.results)?result.results:[];let active=0;
        const activate=index=>{active=index;Array.from(results.children).forEach((item,i)=>item.setAttribute('aria-selected',String(i===active)));if(results.children[active])field.setAttribute('aria-activedescendant',results.children[active].id);};
        const choose=item=>{if(pending||busy)return;loadSeq++;state.name=item.subject;state.parent=String(item.id);selectedMatch=true;$('real-name').value=state.name;$('real-parent').value=state.parent;context=null;$('real-existing').hidden=true;$('real-load-status').textContent='Vybráno. Načti realizaci a řešitele.';hideSuggestions();render();persist();$('real-load').focus();};
        rows.forEach((item,i)=>{const li=document.createElement('li');li.id=field.id+'-option-'+i;li.setAttribute('role','option');li.setAttribute('aria-selected','false');const number=document.createElement('strong');number.textContent='#'+item.id;const title=document.createElement('span');title.textContent=item.subject;li.append(number,title);if(item.status){const status=document.createElement('small');status.textContent=item.status;li.append(status);}li.addEventListener('pointerdown',e=>e.preventDefault());li.addEventListener('click',()=>choose(item));results.append(li);});
        if(!rows.length){$('real-search-status').textContent=result.truncated?'Ve zpracované části nejsou výsledky; hledání nezahrnulo všechny realizace.':'Žádné otevřené realizace neodpovídají.';return;}
        results.hidden=false;field.setAttribute('aria-expanded','true');activate(0);$('real-search-status').textContent=(result.truncated?'Prohledána jen část realizací. ':'')+`Nalezené možnosti: ${rows.length}.`;
        field._realizationKeys=e=>{if(results.hidden)return;if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();activate((active+(e.key==='ArrowDown'?1:rows.length-1))%rows.length);results.children[active].scrollIntoView({block:'nearest'});}else if(e.key==='Enter'){e.preventDefault();choose(rows[active]);}else if(e.key==='Escape'){e.preventDefault();hideSuggestions();}};
      }catch(err){if(sequence===searchSeq){results.hidden=true;field.setAttribute('aria-expanded','false');$('real-search-status').textContent='Hledání se nezdařilo: '+err.message;}}
    },300);
  }
  for(const id of ['real-name','real-parent']){const field=$(id);field.addEventListener('input',()=>suggest(field));field.addEventListener('focus',()=>{if(field.value.trim())suggest(field);});field.addEventListener('keydown',e=>field._realizationKeys?.(e));field.addEventListener('blur',()=>setTimeout(()=>{if(!document.activeElement?.closest('.realization-search'))hideSuggestions();},100));}

  equipment.forEach(input=>input.addEventListener('change',()=>{state.equipment=equipment.filter(x=>x.checked).map(x=>x.value);render();persist();}));
  $('real-bulk-owner').addEventListener('change',()=>{$('real-bulk-apply').disabled=busy||!context||!$('real-bulk-owner').value;});
  $('real-bulk-apply').addEventListener('click',()=>{const id=$('real-bulk-owner').value;if(!context||!context.members.some(m=>String(m.id)===id))return;tasks.forEach(task=>{state.owners[task.id]=id;});render();persist();});

  $('real-select').addEventListener('click',()=>{$('real-output').focus();$('real-output').select();$('real-save-status').textContent='Text je vybraný; zkopíruj jej pomocí Ctrl+C.';});
  $('real-clear').addEventListener('click',()=>{if (pending && !window.confirm('Tento návrh má odeslaný požadavek. Nejprve ověřte výsledek v Redmine. Opravdu odstranit záznam o tomto pokusu?')) return; if (!window.confirm('Zahodit rozpracovaný návrh a začít nový?')) return; pending=null;context=null;loadSeq++;selectedMatch=false;hideSuggestions();$('real-existing').hidden=true;$('real-result').textContent='';$('real-load-status').textContent=''; state.name='';state.parent='';state.equipment=[];state.choices={};state.owners={};state.notes={};$('real-name').value='';$('real-parent').value='';equipment.forEach(input=>{input.checked=false;});render();persist();$('real-name').focus();});
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
    const parent=state.parent.trim(),sequence=++loadSeq;$('real-load').disabled=true;$('real-load-status').textContent='Načítám realizaci a členy projektu…';
    try{const response=await apiFetch('/api/realization-prepare/'+parent),value=await response.json();if(!response.ok)throw Error(value.error||'Načtení se nezdařilo.');if(sequence!==loadSeq||state.parent.trim()!==parent)return;context=value;$('real-load-status').textContent=`#${value.id} · ${value.subject} · ${value.members.length} řešitelů`;const existing=$('real-existing');existing.replaceChildren();const heading=document.createElement('strong');heading.textContent='Již existující dílčí úkoly';existing.append(heading);const ul=document.createElement('ul');value.children.forEach(c=>{const li=document.createElement('li');li.textContent='#'+c.id+' '+c.subject;ul.append(li)});if(!value.children.length){const li=document.createElement('li');li.textContent='Žádné';ul.append(li)}existing.append(ul);existing.hidden=false;render();}
    catch(e){if(sequence===loadSeq){context=null;render();$('real-load-status').textContent='Načtení se nezdařilo: '+e.message;}}finally{$('real-load').disabled=false;}
  });
  $('real-create').addEventListener('click',()=>{
    const active=tasks.filter(t=>relevant(t)&&selected(t));if(!context||pending||!active.length||active.some(t=>!member(t)||taskDescription(t).length>1000))return;
    const suffix=state.name.trim()||context.subject;const taskList=active.map(t=>({subject:t.title+' – '+suffix,description:taskDescription(t),assignee_id:member(t).id}));
    if(taskList.some(t=>t.subject.length>255)){$('real-result').textContent='Název úkolu je příliš dlouhý; zkrať název zakázky.';return;}
    reviewPlan={parent_id:context.id,token:context.token,tasks:taskList};
    $('real-confirm-parent').textContent=`Nadřazená realizace #${context.id}: ${context.subject}`;
    const list=$('real-confirm-list');list.replaceChildren();active.forEach((t,i)=>{const li=document.createElement('li');li.textContent=taskList[i].subject+' — '+member(t).name+(typeof state.notes[t.id]==='string'&&state.notes[t.id].trim()?' · vlastní zpráva: '+state.notes[t.id].trim():'');list.append(li)});
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
