/* Customer selection is manual unless a verified unique match has already
 * been linked by the server-side automatic matching worker. */
(() => {
  'use strict';
  const dialog=document.getElementById('customer-dialog');
  const list=document.getElementById('customer-dialog-list');
  const query=document.getElementById('customer-dialog-query');
  const status=document.getElementById('customer-dialog-status');
  const intro=document.getElementById('customer-dialog-intro');
  if (!dialog || !list || !query || !status) return;

  let current=null, sequence=0, writing=false;
  const fold=value=>String(value||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('cs').trim();

  function candidateButton(entry) {
    const button=document.createElement('button');
    button.type='button';
    button.className='customer-dialog-choice';
    button.dataset.pickCustomer=String(entry.id);
    const title=document.createElement('strong');
    title.textContent=entry.name;
    const detail=document.createElement('small');
    detail.textContent=entry.reason||'Zákazník z projektu Zákazníci · ruční volba';
    button.append(title,detail);
    return button;
  }

  function renderChoices() {
    list.replaceChildren();
    if(!current) return;
    const value=fold(query.value);
    const matches=current.candidates.filter(item=>!value || fold(item.name).includes(value) || String(item.id).includes(value));
    if(!matches.length) {
      const info=document.createElement('p');
      info.textContent=value?'Žádný zákazník neodpovídá hledání.':'Žádný návrh podle kontaktů. Vyhledej zákazníka podle názvu nebo čísla karty.';
      list.append(info);
      return;
    }
    const limited=matches.slice(0,20);
    limited.forEach(item=>list.append(candidateButton(item)));
    if(matches.length>limited.length){
      const note=document.createElement('p');
      note.textContent='Zobrazeno prvních 20 výsledků. Upřesni hledání.';
      list.append(note);
    }
  }

  async function openCustomerDialog(issueId) {
    if(!Number.isSafeInteger(issueId)||issueId<=0||writing)return;
    const token=++sequence;
    current=null;
    query.value='';
    list.replaceChildren();
    status.textContent='Načítám návrhy a seznam zákazníků z Redminu…';
    intro.textContent='Issue #'+issueId+' · propojení vyžaduje tvé potvrzení.';
    if(!dialog.open)dialog.showModal();
    try {
      const response=await apiFetch('/api/helpdesk-suggestions/'+issueId,{method:'POST'});
      const suggestions=await response.json();
      if(!response.ok)throw Error(suggestions.error||'Návrhy se nepodařilo načíst.');
      if(token!==sequence||!dialog.open)return;
      if(Array.isArray(suggestions.linked_customers)&&suggestions.linked_customers.length){
        status.textContent='Tento požadavek už má propojeného zákazníka. Aktualizuj přehled.';
        return;
      }
      const candidateMap=new Map();
      (suggestions.customer_candidates||[]).forEach(item=>{
        if(Number.isSafeInteger(item.id)&&typeof item.name==='string'){
          candidateMap.set(item.id,{id:item.id,name:item.name,reason:'Návrh · '+(item.reason||'vyžaduje potvrzení'),suggested:true});
        }
      });
      let catalogAvailable=false;
      try {
        const allResponse=await apiFetch('/api/redmine-customers',{method:'POST'});
        const allData=await allResponse.json();
        if(!allResponse.ok)throw Error(allData.error||'Katalog není dostupný.');
        if(Array.isArray(allData.customers)){
          catalogAvailable=true;
          allData.customers.forEach(item=>{
            if(Number.isSafeInteger(item.id)&&typeof item.name==='string'&&!candidateMap.has(item.id)){
              candidateMap.set(item.id,{id:item.id,name:item.name,reason:'Karta zákazníka · vyžaduje ruční potvrzení',suggested:false});
            }
          });
        }
      } catch (_) {
        // Suggestions stay usable if the optional full catalog is unavailable.
      }
      if(token!==sequence||!dialog.open)return;
      current={issueId,suggestions,candidates:Array.from(candidateMap.values()).sort((a,b)=>Number(b.suggested)-Number(a.suggested)||a.name.localeCompare(b.name,'cs'))};
      status.textContent=catalogAvailable
        ? 'Návrhy jsou nahoře. Můžeš také vyhledat libovolnou kartu zákazníka.'
        : 'Dostupné jsou pouze návrhy. Úplný seznam zákazníků se nepodařilo načíst.';
      renderChoices();
      query.focus();
    } catch (err) {
      if(token===sequence&&dialog.open)status.textContent='Vyhledávání se nezdařilo: '+err.message;
    }
  }

  document.getElementById('customer-dialog-close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{sequence++;current=null;list.replaceChildren();});
  query.addEventListener('input',renderChoices);
  document.getElementById('list').addEventListener('click',event=>{
    const button=event.target.closest('[data-find-customer]');
    if(button)openCustomerDialog(Number(button.dataset.findCustomer));
  });

  list.addEventListener('click',async event=>{
    const button=event.target.closest('[data-pick-customer]');
    if(!button||!current||writing)return;
    const target=Number(button.dataset.pickCustomer);
    const item=current.candidates.find(c=>c.id===target);
    if(!item)return;
    const id=current.issueId;
    if(!window.confirm('Propojit zákazníka „'+item.name+'“ s požadavkem #'+id+' v Redminu?'))return;
    writing=true;
    query.disabled=true;
    list.querySelectorAll('button').forEach(b=>b.disabled=true);
    status.textContent='Odesílám potvrzené propojení do Redminu…';
    try {
      const response=await apiFetch('/api/helpdesk-apply/'+id,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'customer',target,updated_on:current.suggestions.updated_on,state_token:current.suggestions.state_token})
      });
      const result=await response.json();
      if(!response.ok||!result.ok)throw Error(result.error||'Změnu nelze potvrdit.');
      const issue=data.issues.find(row=>row.id===id);
      if(issue){issue.customers=[{id:target,name:item.name}];issue.customer_suggestions=[];}
      dialog.close();
      render();
      const actionStatus=document.getElementById('action-status');
      if(actionStatus)actionStatus.textContent='Zákazník „'+item.name+'“ byl potvrzen a propojen s požadavkem #'+id+'.';
    }catch(err){
      status.textContent='Propojení nebylo potvrzeno: '+err.message+' Ověř aktuální stav v Redminu.';
    }finally{
      writing=false;
      query.disabled=false;
      list.querySelectorAll('button').forEach(b=>b.disabled=false);
    }
  });
})();
