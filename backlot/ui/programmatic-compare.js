/** EveDirector R8: read-only multi-variant preview, not an Apply surface. */
import {el, getJSON, subscribe} from '/ui/lib.js';
const suffix='/programmatic-compare';
const encoded=location.pathname.startsWith('/p/') && location.pathname.endsWith(suffix)
  ? location.pathname.slice(3,-suffix.length) : '';
const projectId=decodeURIComponent(encoded);
const ep=encodeURIComponent(projectId);
const app=document.getElementById('compare-app');
const matrixQuery=new URLSearchParams(location.search).get('matrix');
let selectedMatrix=matrixQuery || null;
let indexState=null, detail=null, error='', frame=0, players=[];

const text=(x)=>x==null?'—':String(x);
const badge=(name,value)=>el('span',{class:`r8-tag ${String(value).startsWith('PASS')?'r8-tag-pass':String(value).includes('FAIL')?'r8-tag-fail':'r8-tag-warn'}`},`${name}: ${value}`);
function header(){return el('header',{class:'r8-top'},
  el('div',{},el('h1',{},'EveDirector · R8 多平台並列審核'),el('div',{class:'r8-muted'},'Project: '+projectId)),
  el('div',{}, el('span',{class:'r8-pill'},'PREVIEW ONLY · NO APPLY'), '　',
    el('a',{href:`/p/${ep}/agent-review`},'← L4 Review')));
}
function videoCard(item){
  const outer=el('article',{class:'r8-card'},
    el('h2',{},item.profile.replaceAll('_',' ')+' · '+item.format),
    el('div',{class:'r8-muted'},`${item.width}×${item.height} · ${item.provider} · ${item.line_count} 字幕行`));
  const holder=el('div',{class:'r8-video-wrap',style:`aspect-ratio:${item.width}/${item.height}`});
  if(item.media_url){
    const video=el('video',{class:'r8-video',src:item.media_url,preload:'metadata',controls:'',playsinline:''});
    holder.append(video);players.push(video);
    const s=item.safe_area;
    const box=el('div',{class:'r8-safe-overlay',style:
      `left:${100*s.left/item.width}%;right:${100*s.right/item.width}%;`+
      `top:${100*s.top/item.height}%;bottom:${100*s.bottom/item.height}%;`});
    holder.append(box);
  }else holder.append(el('div',{class:'r8-empty'},'未封存影片'));
  outer.append(holder);
  outer.append(el('div',{class:'r8-muted'},'黃色虛線 = 自訂編輯安全矩形，非平台官方認證'));
  const tags=el('div',{class:'r8-tags'});
  for(const [key,val] of Object.entries(item.checks||{}))tags.append(badge(key.replace('_check',''),val));
  outer.append(tags);
  const evidence=el('div',{class:'r8-evidence'},el('b',{},'來源錨點與逐版本雜湊'));
  for(const anchor of item.source_anchors||[]){
    evidence.append(el('div',{},
      el('b',{},`${text(anchor.scene_id)} · source line ${text(anchor.line_start)}`),
      el('p',{},text(anchor.excerpt||anchor.source_contains))));
  }
  const hashes=el('details',{},el('summary',{},'展開 SHA-256 證據'));
  for(const [key,value] of Object.entries(item.proof||{})) hashes.append(el('code',{},`${key}: ${value}`));
  evidence.append(hashes);
  outer.append(evidence);
  return outer;
}
function seekAll(frameNumber){
  if(!detail)return;
  const clamped=Math.max(0,Math.min(detail.sync.frames-1,frameNumber));frame=clamped;
  const time=(frame+.25)/detail.sync.fps;
  for(const player of players){try{player.pause();player.currentTime=time;}catch{ /* media not ready */ }}
  const label=document.getElementById('r8-frame-label');if(label)label.textContent=`Frame ${frame} / ${detail.sync.frames-1} · ${(frame/detail.sync.fps).toFixed(2)}s`;
}
function render(){
  players=[];app.replaceChildren(header());
  app.append(el('div',{class:'r8-notice'},
    '各版本獨立重新驗證 R7→R6→R2 來源與影片指紋。滑桿僅協助在瀏覽器近似定位相同影格，並不保證解碼器逐幀同步、畫素完全一致、官方安全區或發布批准。'));
  if(error)app.append(el('div',{class:'r8-error'},error));
  const rows=indexState?.matrices || [];
  const picker=el('select',{id:'r8-matrix'});
  for(const row of rows)picker.append(el('option',{value:row.matrix_id,disabled:row.status!=='REPLAY_PASS'?'':null},`${row.matrix_id} · ${row.status}`));
  picker.value=selectedMatrix || '';
  picker.addEventListener('change',()=>selectMatrix(picker.value));
  const toolbar=el('div',{class:'r8-toolbar'},el('label',{},'候選矩陣 ',picker));
  if(detail){
    const label=el('span',{id:'r8-frame-label',class:'r8-muted'},`Frame ${frame} / ${detail.sync.frames-1}`);
    const slider=el('input',{type:'range',min:'0',max:String(detail.sync.frames-1),step:'1',value:String(frame),'aria-label':'Preview frame'});
    slider.addEventListener('input',()=>seekAll(Number(slider.value)));
    toolbar.append(el('button',{type:'button',onclick:()=>seekAll(Math.max(0,frame-1))},'−1 frame'),slider,
      el('button',{type:'button',onclick:()=>seekAll(Math.min(detail.sync.frames-1,frame+1))},'+1 frame'),label);
  }
  app.append(toolbar);
  if(detail){
    app.append(el('div',{class:'r8-muted'},`${detail.variants.length} variants · source ${detail.source_sha256} · ${detail.sync.fps} fps · ${detail.sync.frames} frames`));
    const grid=el('main',{class:'r8-grid'},detail.variants.map(videoCard));app.append(grid);
    seekAll(frame);
  } else app.append(el('div',{class:'r8-empty'},rows.length?'Choose a verified matrix.':'No staged R8 compare matrices.'));
}
async function selectMatrix(id){
  selectedMatrix=id;error='';detail=null;frame=0;
  if(!id){render();return;}
  try{detail=await getJSON(`/api/project/${ep}/programmatic-compare/${encodeURIComponent(id)}`);}
  catch(err){error=err.message||String(err);detail=null;}
  render();
}
async function refresh(){
  error='';
  try{
    indexState=await getJSON(`/api/project/${ep}/programmatic-compare`);
    const valid=(indexState.matrices||[]).filter(x=>x.status==='REPLAY_PASS');
    if(!valid.some(x=>x.matrix_id===selectedMatrix))selectedMatrix=valid[0]?.matrix_id||null;
    if(selectedMatrix)await selectMatrix(selectedMatrix);else{detail=null;render();}
  } catch(err){error=err.message||String(err);detail=null;render();}
}
refresh();
subscribe(`/api/project/${ep}/events`,()=>refresh());
