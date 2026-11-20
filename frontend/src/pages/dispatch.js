import {store,load} from '../stores/research.js';
import {dispatch} from '../api/research.js';
import {studySelect} from '../components/common/study-select.js';
import {table} from '../components/common/table.js';
import {bindForm} from '../hooks/forms.js';
import {esc,fmt} from '../utils/format.js';
import {download} from '../utils/download.js';

let state={orders:[],quotas:[],replays:[],replay:null,studyId:0};

const newKey=()=>typeof crypto!=='undefined'&&crypto.randomUUID?crypto.randomUUID():'replay-'+Date.now()+'-'+Math.random().toString(36).slice(2);

async function refreshData(){
  state.studyId=store.studyId||store.studies[0]?.id||0;
  state.orders=state.studyId?await dispatch.orders(state.studyId):[];
  state.quotas=await dispatch.quotas();
  state.replays=await dispatch.listReplays(state.studyId);
}

function orderForm(writable){
  if(!writable)return '';
  return `<h2>补录试印订单</h2><p class="method-note">纸类、班次、到单时刻、读数可见时刻与成对读数均可补录；读数未齐可只填一侧或留空。读数可见时刻用于判断当时是否已能看到该读数。</p><form id="order-form" class="inline-form"><label>源记录编号<input name="source_key" placeholder="如 QM-0001" required></label><label>纸类<input name="paper_type" placeholder="如 米白纸" required></label><label>班次<input name="shift" placeholder="如 白班" required></label><label>到单时刻 (UTC)<input name="arrived_at" type="datetime-local" required></label><label>读数可见时刻 (UTC)<input name="readings_visible_at" type="datetime-local"></label><label>原工艺 ΔE<input name="before" type="number" step="any" min="0"></label><label>新工艺 ΔE<input name="after" type="number" step="any" min="0"></label><button type="submit">保存订单</button><button type="button" id="cancel-order" hidden>取消编辑</button></form>`;
}

function quotaForm(quotas,writable){
  if(!writable)return '';
  return `<h2>每班新工艺名额</h2><form id="quota-form" class="inline-form"><label>班次<input name="shift" placeholder="如 白班" required></label><label>名额<input name="quota" type="number" min="0" step="1" value="1" required></label><button type="submit">设置名额</button></form>${table(['班次','名额','更新时间'],quotas.map(q=>[q.shift,q.quota,q.updated_at]))}`;
}

function replayPanel(writable){
  if(!writable)return '';
  return `<h2>回放名额派单</h2><p class="method-note">冻结当时的订单、门槛与班次名额，按到单顺序逐单重放。同一回放请求（幂等键相同）重试不会新增记录，也不会改用之后补录的数据。冻结时刻留空表示以服务器当前时刻为准。</p><form id="replay-form" class="worksheet"><div class="inline-form"><label>回放名称<input name="name" required minlength="2" value="名额派单回放"></label><label>冻结时刻 (UTC)<input name="as_of" type="datetime-local"></label><label>平均改善门槛 ΔE<input name="threshold" type="number" step="any" value="0.3" required></label><input type="hidden" name="idempotency_key" value="${newKey()}"></div><button type="submit">冻结并回放 →</button></form>`;
}

function replayResult(replay){
  if(!replay)return '';
  const r=replay.result,c=r.comparison;
  const pct=x=>x===null?'—':fmt(x);
  const selected=r.selected;
  return `<h2>回放 #${replay.id} · ${esc(replay.name)}</h2><div class="checksum">INPUT SHA256 ${replay.checksum}</div><p>冻结时刻 ${esc(replay.as_of)} · 门槛 ${fmt(replay.threshold)} · ${replay.replay_existing?'该幂等键已存在，返回既有冻结结果，未新增':esc(replay.created_at)}</p><section class="result-intro"><strong>按此派单平均色差 ${pct(c.dispatch_mean_delta_e)} ΔE · 全走原工艺 ${pct(c.all_original_mean_delta_e)} ΔE · 差额 ${pct(c.difference)} ΔE</strong><p>计入对比 ${c.orders_counted} 单（未齐读数 ${c.orders_excluded_incomplete} 单两侧均不计）；选中新工艺 ${c.selected_count} 单。已占名额未因读数未齐而退回。</p></section><h2>选中的订单 <small>${selected.length} 单</small></h2>${table(['订单','纸类','班次','到单时刻','本班余额(前/后)','依据单数','依据平均改善','读数是否已齐'],selected.map(d=>[d.source_key,d.paper_type,d.shift,d.arrived_at,`${d.quota_before} / ${d.quota_after}`,d.basis_count,fmt(d.average_improvement),d.counted?'已齐':'未齐(占名额)']))}<h2>班次名额</h2>${table(['班次','名额','已选','剩余'],r.shifts.map(s=>[s.shift,s.quota,s.selected,s.remaining]))}<h2>逐单派单明细</h2>${table(['订单','纸类 / 班次','到单时刻','原工艺ΔE','新工艺ΔE','派单','依据平均改善','计入对比','说明'],r.decisions.map(d=>[d.source_key,`${d.paper_type} / ${d.shift}`,d.arrived_at,d.before===null?'未齐':fmt(d.before),d.after===null?'未齐':fmt(d.after),d.selected?'新工艺':'原工艺',d.average_improvement===null?'—':fmt(d.average_improvement),d.counted?'是':'否',d.note?d.reason+'；'+d.note:d.reason]))}<div class="toolbar"><button id="export-replay">下载回放 CSV</button></div>`;
}

export async function render(){
  await refreshData();
  const writable=localStorage.getItem('research-role')!=='viewer';
  return `<div class="eyebrow">03B / ALLOCATION REPLAY</div><h1>新工艺名额派单回放</h1><p class="lead">用试印记录回放当时该把名额给谁：逐单按到单顺序处理，同刻按编号；用当时已齐的较早同类订单算平均改善，超过门槛且本班有名额才选新工艺，无依据就走原工艺。</p><div class="method-note">读数未齐（缺任一侧或可见时刻未到）的订单，两套平均都不计，但已经占用的名额照扣。</div><div class="toolbar">${studySelect()}</div>
  ${orderForm(writable)}
  <h2>试印订单 <small>${state.orders.length} 条</small></h2>${table(['源记录','纸类','班次','到单时刻','读数可见时刻','原工艺ΔE','新工艺ΔE',...(writable?['操作']:[])],state.orders.map(o=>[o.source_key,o.paper_type,o.shift,o.arrived_at,o.readings_visible_at||'未齐',o.before===null?'—':fmt(o.before),o.after===null?'—':fmt(o.after),...(writable?[{html:`<button class="text" data-edit-order="${o.id}">编辑</button> <button class="text" data-delete-order="${o.id}">移除</button>`}]:[])]))}
  ${quotaForm(state.quotas,writable)}
  ${replayPanel(writable)}
  <h2>历史回放</h2>${table(['编号','名称','冻结时刻','门槛','计入单数','选中单数','派单平均ΔE','全原工艺平均ΔE','操作'],state.replays.map(x=>[`#${x.id}`,esc(x.name),x.as_of,fmt(x.threshold),x.result.comparison.orders_counted,x.result.comparison.selected_count,fmt(x.result.comparison.dispatch_mean_delta_e),fmt(x.result.comparison.all_original_mean_delta_e),{html:`<button class="text" data-view-replay="${x.id}">查看</button>`}]))}
  ${replayResult(state.replay)}`;
}

export function bind(refresh){
  const sel=document.getElementById('study-select');if(sel)sel.onchange=async()=>{store.studyId=+sel.value;state.replay=null;refresh();};
  const writable=localStorage.getItem('research-role')!=='viewer';
  let editing=null;
  bindForm('order-form',async data=>{const before=data.before===''?null:+data.before;const after=data.after===''?null:+data.after;if(!state.studyId)throw new Error('请先选择试印研究');const body={source_key:data.source_key,paper_type:data.paper_type,shift:data.shift,arrived_at:toIso(data.arrived_at),readings_visible_at:data.readings_visible_at?toIso(data.readings_visible_at):null,before,after};await dispatch.saveOrder(state.studyId,body,editing);await load();refresh();});
  bindForm('quota-form',async data=>{await dispatch.setQuota(data.shift,+data.quota);refresh();});
  bindForm('replay-form',async data=>{const body={study_id:state.studyId,name:data.name,threshold:+data.threshold,idempotency_key:data.idempotency_key};if(data.as_of)body.as_of=toIso(data.as_of);const r=await dispatch.createReplay(body);state.replay=r;refresh();});
  if(writable){
    document.querySelectorAll('[data-edit-order]').forEach(el=>el.onclick=()=>{const o=state.orders.find(x=>x.id===+el.dataset.editOrder),form=document.getElementById('order-form');editing=o.id;form.elements.source_key.value=o.source_key;form.elements.paper_type.value=o.paper_type;form.elements.shift.value=o.shift;form.elements.arrived_at.value=fromIso(o.arrived_at);form.elements.readings_visible_at.value=o.readings_visible_at?fromIso(o.readings_visible_at):'';form.elements.before.value=o.before===null?'':o.before;form.elements.after.value=o.after===null?'':o.after;document.getElementById('cancel-order').hidden=false;form.scrollIntoView({behavior:'smooth',block:'center'});});
    document.querySelectorAll('[data-delete-order]').forEach(el=>el.onclick=async()=>{try{await dispatch.removeOrder(state.studyId,+el.dataset.deleteOrder);await load();refresh();}catch(e){document.getElementById('notice').textContent=e.message;}});
  }
  const cancel=document.getElementById('cancel-order');if(cancel)cancel.onclick=()=>refresh();
  document.querySelectorAll('[data-view-replay]').forEach(el=>el.onclick=async()=>{state.replay=await dispatch.getReplay(+el.dataset.viewReplay);refresh();});
  const exp=document.getElementById('export-replay');if(exp)exp.onclick=async()=>{try{download(await dispatch.exportReplay(state.replay.id),'dispatch-replay-'+state.replay.id+'.csv');}catch(e){document.getElementById('notice').textContent=e.message;}};
}

function toIso(local){if(!local)return null;const text=local.length===16?local+':00':local;return /[zZ]|[+-]\d\d:\d\d$/.test(text)?text:text+'Z';}
function fromIso(value){const d=new Date(value);const pad=n=>String(n).padStart(2,'0');return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;}
