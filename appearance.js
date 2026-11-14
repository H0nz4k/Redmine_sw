(() => {
  const defaults={size:14,bold:false,theme:'light'};
  let state={...defaults};
  try { const value=JSON.parse(localStorage.getItem('redmine-appearance-v1')||'{}'); if([13,14,16,18].includes(value.size))state.size=value.size;if(typeof value.bold==='boolean')state.bold=value.bold;if(['light','blue','dark'].includes(value.theme))state.theme=value.theme; } catch (_) {}
  const apply=()=>{const root=document.documentElement;root.style.setProperty('--ui-size',state.size+'px');root.dataset.bold=String(state.bold);root.dataset.theme=state.theme;};
  const save=()=>{apply();try{localStorage.setItem('redmine-appearance-v1',JSON.stringify(state));}catch(_){}};
  apply();
  document.addEventListener('DOMContentLoaded',()=>{
    const panel=document.querySelector('#appearance-settings');if(!panel)return;
    function sync(){panel.querySelectorAll('[data-size]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.size)===state.size)));panel.querySelectorAll('[data-theme-choice]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeChoice===state.theme)));panel.querySelector('#appearance-bold').checked=state.bold;}
    panel.addEventListener('click',event=>{const size=event.target.closest('[data-size]');const theme=event.target.closest('[data-theme-choice]');if(size)state.size=Number(size.dataset.size);else if(theme)state.theme=theme.dataset.themeChoice;else if(event.target.closest('#appearance-reset'))state={...defaults};else return;save();sync();});
    panel.querySelector('#appearance-bold').addEventListener('change',event=>{state.bold=event.target.checked;save();sync();});
    document.addEventListener('click',event=>{if(panel.open&&!panel.contains(event.target))panel.open=false;});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&panel.open){panel.open=false;panel.querySelector('summary').focus();}});
    sync();
  });
})();
