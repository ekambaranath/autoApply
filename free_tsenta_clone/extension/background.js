chrome.action.onClicked.addListener(async (tab) => {
  try {
    const r=await fetch('http://127.0.0.1:8000/api/jobs/from-page',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:tab.url,title:tab.title||'',text:''})});
    const data=await r.json();
    chrome.scripting.executeScript({target:{tabId:tab.id},func:(msg)=>alert(msg),args:[`Career Agent: job imported (${data.id||'unknown'})`]});
  } catch(e) { chrome.scripting.executeScript({target:{tabId:tab.id},func:()=>alert('Start the local Career Agent first.')}); }
});
