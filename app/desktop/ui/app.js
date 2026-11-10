"use strict";
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let cautionOptions = null, cautionSelection = {conditions:[], medications:[]}, cautionRevision = 0;
let cautionOptionsReady = null;
const cautionMatches = new WeakMap();
let bridge, nextId = 0, revision = 0, report = null, rows = [], toastTimer;
const pending = new Map();
const uid = () => "row-" + (++nextId);
function api(action, data = {}) {
  return new Promise((resolve, reject) => {
    if (!bridge) return reject(new Error("앱 연결을 준비 중입니다. 잠시 후 다시 시도해 주세요."));
    const id = "req-" + (++nextId);
    pending.set(id, {resolve, reject});
    bridge.request(JSON.stringify({id, action, data}));
  });
}
function toast(message, error = false) {
  $("toast").textContent = message; $("toast").className = "toast" + (error ? " error" : "");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $("toast").classList.add("hidden"), error ? 7000 : 4200);
}
function invalidate() {
  revision++; report = null; $("issues").classList.add("hidden");
  $("report-content").classList.add("hidden"); $("empty-report").classList.remove("hidden");
  updateExport(); updateSummary();
}
function newRow(source = {}) {
  return {component_id: uid(), name:"", query:"", mode:"name", canonical_smiles:"", amount_pct:null,
    amount_text:"", preview:"", source:"", confirmed:false, token:0, ...source, component_id:uid()};
}
function payload() {
  return {schema_version:1, name:$("formulation-name").value.trim(), scope:$("scope").value,
    unit:"% w/w", components:rows.map(r => ({
      component_id:r.component_id, name:r.name || r.query, query:r.query, mode:r.mode,
      canonical_smiles:r.canonical_smiles, amount_pct:r.amount_pct, amount_text:r.amount_text,
      source:r.source || "", source_url:r.source_url || "", cas:r.cas || ""
    }))};
}
function changePage(which) {
  const input = which === "input";
  $("input-page").classList.toggle("hidden", !input); $("report-page").classList.toggle("hidden", input);
  $("nav-input").classList.toggle("active", input); $("nav-report").classList.toggle("active", !input);
  $("breadcrumb").textContent = input ? "원료 배합 분석" : "분석 보고서";
  window.scrollTo(0,0);
}
function updateSummary() {
  const total = rows.reduce((n,r)=>n+(Number.isFinite(r.amount_pct) ? r.amount_pct:0),0);
  const missing = rows.some(r=>!Number.isFinite(r.amount_pct));
  const resolved = rows.filter(r=>r.canonical_smiles).length;
  $("total").textContent = total.toLocaleString("en-US",{maximumFractionDigits:3});
  $("composition-fill").style.width = Math.max(0, Math.min(100,total)) + "%";
  $("composition-fill").parentElement.classList.toggle("over", total>100.000000001);
  $("ingredient-count").textContent = rows.length + "개"; $("summary-count").textContent = rows.length + "개";
  $("resolved-count").textContent = resolved + " / " + rows.length;
  $("unlisted").textContent = missing ? "함량 확인 필요" : (total>100 ? "합계 초과" : Number((100-total).toFixed(4))+"%");
  $("scope-caption").textContent = $("scope").value === "complete" ? "전체 배합은 함량 합계 100%가 필요합니다." : "일부 조성의 결과는 입력된 원료에 한정됩니다.";
}
function renderRows() {
  $("rows").innerHTML = rows.map((r,i) => '<tr data-row="'+esc(r.component_id)+'"><td>'+String(i+1).padStart(2,"0")+
    '</td><td><div class="ingredient-input"><select aria-label="'+(i+1)+'번 입력 방식" data-field="mode"><option value="name"'+(r.mode==="name"?" selected":"")+'>성분명 / CAS</option><option value="smiles"'+(r.mode==="smiles"?" selected":"")+'>SMILES</option></select><input data-field="query" aria-label="'+(i+1)+'번 원료" value="'+esc(r.query)+'" placeholder="'+(r.mode==="name"?"성분명 또는 CAS":"예: CCO")+'"></div><div class="ingredient-meta">'+esc(r.canonical_smiles ? ((r.name||"구조 입력됨")+" · "+r.canonical_smiles) : "구조를 확인해 주세요")+
    '</div></td><td><input class="amount-input" data-field="amount" inputmode="decimal" aria-label="'+(i+1)+'번 함량" placeholder="0.00" value="'+esc(r.amount_text || (r.amount_pct==null?"":r.amount_pct))+
    '"></td><td><button class="resolve-button '+(r.canonical_smiles?"resolved":"")+'" data-action="resolve">'+(r.canonical_smiles?"구조 보기":"구조 확인")+
    '</button>'+(r.preview?'<img class="row-preview" src="'+esc(r.preview)+'" alt="원료 분자 구조">':"")+
    '</td><td><button class="icon-button" data-action="remove" aria-label="'+(i+1)+'번 원료 삭제">×</button></td></tr>').join("");
  updateSummary();
}
$("rows").addEventListener("input", event => {
  const element = event.target, tr = element.closest("[data-row]"); if (!tr) return;
  const r = rows.find(x=>x.component_id===tr.dataset.row); if (!r) return;
  if (element.dataset.field === "amount") {
    r.amount_text = element.value;
    r.amount_pct = element.value.trim() !== "" && Number.isFinite(Number(element.value)) ? Number(element.value) : null;
  } else if (element.dataset.field === "query") {
    r.query = element.value; r.name=""; r.canonical_smiles=""; r.preview=""; r.confirmed=false; r.token++;
    tr.querySelector(".ingredient-meta").textContent = "구조를 확인해 주세요.";
    tr.querySelector(".resolve-button").textContent = "구조 확인"; tr.querySelector(".resolve-button").classList.remove("resolved");
    const img = tr.querySelector(".row-preview"); if (img) img.remove();
  }
  invalidate();
});
$("rows").addEventListener("change", event => {
  if (event.target.dataset.field !== "mode") return;
  const r = rows.find(x=>x.component_id===event.target.closest("[data-row]").dataset.row);
  r.mode = event.target.value; r.canonical_smiles=""; r.preview=""; r.name=""; r.confirmed=false; r.token++;
  invalidate(); renderRows();
});
$("rows").addEventListener("click", event => {
  const button = event.target.closest("[data-action]"); if (!button) return;
  const id = button.closest("[data-row]").dataset.row;
  if (button.dataset.action === "remove") { rows = rows.filter(r=>r.component_id!==id); if(!rows.length) rows=[newRow()]; invalidate(); renderRows(); }
  else resolveRow(id, button);
});
async function resolveRow(id, button) {
  const r = rows.find(x=>x.component_id===id); if(!r) return;
  const token = ++r.token;
  button.disabled=true; button.textContent="확인 중…";
  try {
    const candidates = r.canonical_smiles && (!r.name||r.name==="직접 입력 원료") ? [{...await api("structure",{smiles:r.canonical_smiles}),name:"직접 입력 원료",source:r.source,cas:""}] :
      r.canonical_smiles ? await api("lookup",{query:r.name||r.query,mode:"name"}) :
      await api("lookup",{query:r.query,mode:r.mode});
    if (!rows.includes(r) || r.token !== token) return;
    $("candidates").innerHTML = candidates.map((c,i)=>'<article class="candidate"><div class="candidate-top"><img src="'+esc(c.preview)+'" alt="후보 구조"><div><strong>'+esc(c.name)+'</strong><p>'+esc(c.cas || (c.cid?"PubChem CID "+c.cid:c.source))+'</p><p>'+esc(c.canonical_smiles)+'</p></div></div><button class="button primary" data-candidate="'+i+'">이 구조 사용하기</button></article>').join("");
    $("candidates").querySelectorAll("[data-candidate]").forEach(b=>b.addEventListener("click",()=>{
      if (rows.includes(r) && r.token === token) {
        Object.assign(r,candidates[Number(b.dataset.candidate)],{confirmed:true});
        if(r.mode==="smiles") r.name = r.query === r.canonical_smiles ? "직접 입력 원료" : (r.name || "직접 입력 원료");
        invalidate(); renderRows();
      }
      $("candidate-dialog").close();
    }));
    $("candidate-dialog").showModal();
  } catch(e) { toast(e.message,true); }
  finally { if(document.contains(button)) {button.disabled=false;button.textContent=r.canonical_smiles?"구조 보기":"구조 확인";} }
}
const CAUTION_TIER={strong:"근거 강함",moderate:"근거 보통",mixed:"근거 혼재",advisory:"참고"};
const CAUTION_TYPE={DDI:"약물 효과 저하(DDI)",ADR:"자극·이상반응 증폭(ADR)",PHOTOTOXIC:"광독성 중첩"};
function renderCautionOptions(){
  const options=relatedCautionOptions();
  const box=(kind,item)=>'<label class="caution-option'+(cautionSelection[kind].includes(item.id)?" on":"")+'" title="'+esc(item.description_ko)+'"><input type="checkbox" data-caution="'+kind+'" value="'+esc(item.id)+'"'+(cautionSelection[kind].includes(item.id)?" checked":"")+'><span>'+esc(item.label_ko)+'<small>'+(item.domain==="eye"?"눈":"피부")+'</small></span></label>';
  let visibleGroups=0,selectedGroups=0;
  ["conditions","medications"].forEach(kind=>{
    const container=$("caution-"+kind),group=container.closest('.caution-group');
    container.innerHTML=options[kind].map(item=>box(kind,item)).join("");
    group.classList.toggle('hidden',!options[kind].length);
    const selected=options[kind].some(item=>cautionSelection[kind].includes(item.id));
    group.classList.toggle('has-selection',selected);
    if(options[kind].length)visibleGroups++;
    if(selected)selectedGroups++;
  });
  $("caution-picker").classList.toggle('hidden',!visibleGroups);
  $("caution-picker").classList.toggle('single-group',visibleGroups===1);
  $("caution-picker").classList.toggle('has-selection',selectedGroups>0);
  $("caution-picker").classList.toggle('single-selection',selectedGroups===1);
}
function relatedCautionOptions(){
  const result=report&&cautionMatches.get(report)?.result;
  if(!result||!cautionOptions)return {conditions:[],medications:[]};
  return {
    conditions:cautionOptions.conditions.filter(item=>result.results?.[item.id]?.cautions?.length>0),
    medications:cautionOptions.medications.filter(item=>result.medication_results?.[item.id]?.interactions?.length>0)
  };
}
document.addEventListener("change",event=>{
  const kind=event.target.dataset&&event.target.dataset.caution; if(!kind)return;
  cautionSelection[kind]=Array.from(document.querySelectorAll('[data-caution="'+kind+'"]:checked'),e=>e.value);
  event.target.closest(".caution-option").classList.toggle("on",event.target.checked);
  refreshCaution();
});
function cautionPayload(){return {conditions:[...cautionSelection.conditions],medications:[...cautionSelection.medications]};}
function refreshCaution(){
  // Evaluate registered rules once per report; keep only the user's relevant choices in exports.
  if(!report)return Promise.resolve();
  const version=++cautionRevision, current=report;
  let state=cautionMatches.get(current);
  if(!state){
    state={loading:true};cautionMatches.set(current,state);
    state.promise=(async()=>{
      if(!cautionOptions)await cautionOptionsReady;
      if(!cautionOptions)throw new Error("주의정보 목록을 불러오지 못했습니다.");
      const all={conditions:cautionOptions.conditions.map(item=>item.id),medications:cautionOptions.medications.map(item=>item.id)};
      const result=await api("caution",{input:current.input,caution:all});
      if(result.status!=="complete")throw new Error((result.reasons||["관련 주의정보를 확인하지 못했습니다."]).join(" / "));
      state.result=result;state.loading=false;return result;
    })().catch(error=>{state.error=error.message;state.loading=false;throw error;});
  }
  const apply=()=>{
    if(version!==cautionRevision||report!==current)return;
    const options=relatedCautionOptions();
    ["conditions","medications"].forEach(kind=>{
      const available=new Set(options[kind].map(item=>item.id));
      cautionSelection[kind]=cautionSelection[kind].filter(id=>available.has(id));
    });
    const selection=cautionPayload();
    current.caution={...state.result,...selection,
      status:selection.conditions.length||selection.medications.length?"complete":"not_selected",
      results:Object.fromEntries(selection.conditions.map(id=>[id,state.result.results[id]])),
      medication_results:Object.fromEntries(selection.medications.map(id=>[id,state.result.medication_results[id]]))};
    renderCautionOptions();renderCaution();updateExport();
    return current.caution;
  };
  if(state.result){window.cautionReady=Promise.resolve(apply());return window.cautionReady;}
  renderCautionOptions();renderCaution();updateExport();
  window.cautionReady=state.promise.then(apply).catch(error=>{
    if(version!==cautionRevision||report!==current)return;
    current.caution={status:"held",reasons:[error.message]};
    renderCautionOptions();renderCaution();updateExport();
  });
  return window.cautionReady;
}
function setCautionSelection(selection){
  const known=(kind)=>cautionOptions?cautionOptions[kind].map(x=>x.id):null;
  const clean=(kind)=>{const list=Array.isArray(selection&&selection[kind])?selection[kind].map(String):[];const ids=known(kind);return ids?list.filter(x=>ids.includes(x)):list;};
  cautionSelection={conditions:clean("conditions"),medications:clean("medications")};renderCautionOptions();
}
function renderCaution(){
  const c=report.caution, body=$("caution-body");
  const state=cautionMatches.get(report);
  const coverage=state?.result||c;
  const unmatched=!state?.loading&&!state?.error?(coverage?.unmatched_components||[]):[];
  const names=[...new Set(unmatched.map(item=>item.display_name||item.name||item.canonical_smiles||"이름 없는 원료"))];
  const hasCoverage=!state?.loading&&!state?.error&&Number.isInteger(coverage?.recognized_component_count);
  $("caution-coverage").textContent=hasCoverage?"사전 확인 "+coverage.recognized_component_count+"개 / 미확인 "+unmatched.length+"개":"";
  $("caution-coverage").classList.toggle("hidden",!hasCoverage);
  $("caution-unmatched").textContent=names.length?"사전에 없어서 확인하지 못한 원료: "+names.join(", "):"";
  $("caution-unmatched").classList.toggle("hidden",!names.length);
  if(state?.loading){body.innerHTML='<div class="caution-empty">원료와 관련된 주의정보를 확인하고 있습니다…</div>';return;}
  if(state?.error){
    body.innerHTML='<div class="caution-empty">주의정보를 확인하지 못했습니다: '+esc(state.error)+' <button id="retry-caution" class="button secondary">다시 확인</button></div>';
    $("retry-caution").onclick=()=>{cautionMatches.delete(report);refreshCaution();};return;
  }
  const options=relatedCautionOptions();
  if(state?.result&&!options.conditions.length&&!options.medications.length){
    body.innerHTML=coverage.recognized_component_count===0?"":'<div class="caution-empty">'+(names.length?"사전에서 확인된 원료에서는":"입력 원료와")+' 매칭된 주의정보가 없습니다.</div>';return;
  }
  if(!c){body.innerHTML='<p class="muted">이 보고서에는 주의정보가 없습니다.</p>';return;}
  if(c.status==="not_selected"){body.innerHTML='<div class="caution-empty">위에서 해당하는 상태나 병용 약물을 선택하면 결과가 여기에 표시됩니다.</div>';return;}
  if(c.status!=="complete"){body.innerHTML='<div class="caution-empty">주의정보를 확인하지 못했습니다: '+esc((c.reasons||[]).join(" / "))+'</div>';return;}
  const matched=(item)=>item.matched_components.map(m=>esc(m.name)+(m.amount_pct!=null?" <small>"+esc(m.amount_pct)+"%</small>":"")).join(", ");
  const cites=(item)=>item.citations.length?'<details class="caution-cites"><summary>근거 문헌 '+item.citations.length+'건</summary><ul>'+item.citations.map(x=>'<li><a href="'+esc(x.url)+'">'+esc(x.title)+'</a></li>').join("")+'</ul></details>':"";
  const finding=(item,badge,cls)=>'<li class="caution-item"><div class="caution-item-top"><span class="caution-badge '+cls+'">'+esc(badge)+'</span><strong>'+esc(item.label_ko)+'</strong></div><p class="caution-matched">검출 성분: '+matched(item)+'</p><p>'+esc(item.message_ko)+'</p>'+cites(item)+'</li>';
  const card=(entry,list,kindLabel)=>'<article class="caution-card'+(entry.no_findings?" clear":"")+'"><div class="caution-card-head"><span class="caution-kind">'+kindLabel+' · '+(entry.domain==="eye"?"눈":"피부")+'</span><h3>'+esc(entry.label_ko)+'</h3></div>'+
    (entry.no_findings?'<p class="caution-none">등록된 주의 성분이 이 배합에서 검출되지 않았습니다.<small>사전에 없는 표기·동의어는 놓칠 수 있으며, 안전하다는 뜻은 아닙니다.</small></p>':'<ul class="caution-list">'+list+'</ul>')+'</article>';
  let html='<p class="caution-disclaimer">'+esc(c.disclaimer)+'</p><div class="caution-grid">';
  Object.values(c.results||{}).forEach(e=>{html+=card(e,e.cautions.map(i=>finding(i,CAUTION_TIER[i.evidence_tier]||i.evidence_tier,"tier-"+i.evidence_tier)).join(""),"상태");});
  Object.values(c.medication_results||{}).forEach(e=>{html+=card(e,e.interactions.map(i=>finding(i,CAUTION_TYPE[i.interaction_type]||i.interaction_type,"type-"+i.interaction_type)).join(""),"병용 약물");});
  body.innerHTML=html+'</div>';
}
function loadExample() {
  $("formulation-name").value="분자구조·보조점수 시연 예제"; $("scope").value="complete";
  rows=[
    ["레티놀","CC1=C(C(CCC1)(C)C)/C=C/C(=C/C=C/C(=C/CO)/C)/C",0.3],
    ["리모넨","CC1=CCC(CC1)C(=C)C",0.1],
    ["소듐라우릴설페이트","CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]",1],
    ["에탄올","CCO",20],
    ["글리세린","OCC(O)CO",5],
    ["정제수","O",73.6]
  ].map(([name,canonical_smiles,amount_pct])=>newRow({name,query:name,canonical_smiles,amount_pct,source:"시연용 예제"}));
  setCautionSelection({conditions:["atopic_dermatitis"],medications:["isotretinoin_oral"]});
  invalidate();renderRows();toast("시연용 예제를 불러왔습니다. 제품 배합 권고가 아닙니다.");
}
async function runAnalysis() {
  const snapshot = payload(), version = revision;
  $("analyze").disabled=true;
  try {
    const validation = await api("validate",snapshot);
    if(revision!==version) return;
    if(!validation.valid) {
      $("issues").innerHTML="<strong>입력을 확인해 주세요.</strong><ul>"+validation.issues.map(i=>"<li>"+esc(i.message)+"</li>").join("")+"</ul>";
      $("issues").classList.remove("hidden"); return;
    }
    $("busy-overlay").classList.remove("hidden");
    const result = await api("analyze",{...snapshot,caution:cautionPayload()});
    if(revision!==version) return;
    if(result.status!=="complete") {
      const issues=result.validation?.issues||[{message:"입력이 올바르지 않아 분석을 진행하지 못했습니다."}];
      $("issues").innerHTML="<strong>입력을 확인해 주세요.</strong><ul>"+issues.map(i=>"<li>"+esc(i.message)+"</li>").join("")+"</ul>";
      $("issues").classList.remove("hidden");return;
    }
    report=result; renderReport(); changePage("report");
    await window.cautionReady;
    if(revision!==version||report!==result)return;
    return report;
  } catch(e) {toast(e.message,true);}
  finally {$("busy-overlay").classList.add("hidden");$("analyze").disabled=false;}
}
function updateExport(){const waiting=report&&cautionMatches.get(report)?.loading;["export-json","export-csv","export-pdf"].forEach(id=>$(id).disabled=!report||!!waiting);}
function renderReport(){
  if(!report)return;
  $("empty-report").classList.add("hidden");$("report-content").classList.remove("hidden");updateExport();
  $("report-title").textContent=report.input.name || "이름 없는 배합";
  const date = new Date(report.created_at).toLocaleString("ko-KR");
  $("report-date").textContent=date;
  $("report-subtitle").textContent="입력한 원료의 특징과 함량을 반영한 연구용 분석 결과";
  $("report-summary").innerHTML=[["입력 범위",report.input.scope==="complete"?"전체 배합":"공개된 일부 조성"],["원료 수",report.input.components.length+"개"],
    ["함량 합계",Number(report.validation.total.toFixed(4))+"%"],["미기재",Number(report.validation.unlisted.toFixed(4))+"%"]]
    .map(([a,b])=>"<div><span>"+esc(a)+"</span><strong>"+esc(b)+"</strong></div>").join("");
  $("result-cards").innerHTML=["skin","eye"].map(endpoint=>{
    const r=report.results[endpoint],isSkin=endpoint==="skin";
    let html='<article class="result-card '+(r.predicted_class===1?"positive":"")+'"><div class="result-heading"><span class="model-symbol '+(isSkin?"":"eye")+'">'+(isSkin?"S":"E")+'</span><h2>'+(isSkin?"피부자극":"안자극")+'</h2><small>'+esc(r.model_name || (isSkin?"Random Forest":"Logistic Regression"))+'</small></div>';
    if(r.status!=="complete") return html+'<span class="result-label positive">판단 보류</span><div class="held-reasons">'+esc((r.reasons||[]).join(" / "))+'</div><p>다른 모델의 결과는 독립적으로 확인할 수 있습니다.</p></article>';
    html+='<div class="result-label '+(r.predicted_class===1?"positive":"")+'">'+esc(r.label_text)+' 예측</div><div class="score">'+r.score.toFixed(4)+'<small>모델 점수</small></div><div class="gauge" data-score="'+r.score+'" data-threshold="'+r.threshold+'"><div class="gauge-fill"></div><div class="gauge-marker"></div></div><div class="gauge-meta"><span>0</span><span>판정 임계값 '+r.threshold.toFixed(4)+'</span><span>1</span></div></article>';return html;
  }).join("");
  document.querySelectorAll(".gauge").forEach(g=>{g.querySelector(".gauge-fill").style.width=(Number(g.dataset.score)*100)+"%";g.querySelector(".gauge-marker").style.left=(Number(g.dataset.threshold)*100)+"%";});
  const weights=new Map(report.weights.map(w=>[w.component_id,w.relative_weight]));
  const visibleWarnings=(report.validation.warnings||[]).filter(message=>!/^미기재 .+%는 추정하거나 물로 채우지 않습니다\.$/.test(message));
  $("report-ingredients").innerHTML='<div class="table-wrap"><table class="report-table"><thead><tr><th>원료</th><th>SMILES</th><th>함량</th><th>상대 가중치</th><th>상태</th></tr></thead><tbody>'+report.input.components.map(r=>'<tr><td>'+esc(r.name||"직접 입력 원료")+'</td><td><code>'+esc(r.canonical_smiles)+'</code></td><td>'+esc(r.amount_pct)+'%</td><td>'+(weights.has(r.component_id)?weights.get(r.component_id).toFixed(4):"—")+'</td><td>'+(r.amount_pct===0?"0% · 제외":"계산 대상")+'</td></tr>').join("")+'</tbody></table></div>'+
    (visibleWarnings.length?'<p class="muted">'+visibleWarnings.map(esc).join("<br>")+'</p>':"");
  const versions=[["분석 시간",date],["앱 버전",report.app_version],["입력 기록",report.input_hash]];
  ["skin","eye"].forEach(ep=>{const r=report.results[ep];versions.push([ep==="skin"?"피부 모델":"눈 모델",r.model_id||"실행 보류"]);if(r.model_sha256)versions.push(["SHA-256",r.model_sha256]);});
  $("version-details").innerHTML=versions.map(([a,b])=>'<div class="version-item"><span>'+esc(a)+'</span><code>'+esc(b)+'</code></div>').join("");
  refreshCaution();
  renderEvidencePanel();
}
function hydrate(data){
  $("formulation-name").value=String(data.name||"").slice(0,100);$("scope").value=data.scope==="complete"?"complete":"partial";
  setCautionSelection(data.caution);
  rows=data.components.map(r=>newRow({...r,query:r.query||r.name||r.canonical_smiles||"",mode:r.mode||(r.name?"name":"smiles"),preview:"",confirmed:false}));
  invalidate();renderRows();changePage("input");
}
async function save(action){
  if(action!=="save_draft"&&!report)return;
  // Images are rendered in the PDF. Structured exports retain scores, patterns and sources.
  const data=action==="save_draft"?payload():JSON.parse(JSON.stringify(report,(key,value)=>key==="preview"?undefined:value));
  try{const response=await api(action,data);if(response&&!response.printing)toast("저장했습니다: "+response.path);}catch(e){toast(e.message,true);}
}
window.pdfFinished=(path)=>toast(path?"PDF를 저장했습니다: "+path:"PDF를 저장하지 못했습니다.",!path);
$("nav-input").onclick=()=>changePage("input");$("nav-report").onclick=()=>changePage("report");
$("start-input").onclick=()=>changePage("input");$("edit-input").onclick=()=>changePage("input");
$("formulation-name").oninput=invalidate;$("scope").onchange=invalidate;
$("add-row").onclick=()=>{if(rows.length>=100)return toast("최대 100개 원료를 입력할 수 있습니다.",true);rows.push(newRow());invalidate();renderRows();};
$("load-example").onclick=loadExample;$("analyze").onclick=runAnalysis;$("close-dialog").onclick=()=>$("candidate-dialog").close();
$("save-draft").onclick=()=>save("save_draft");$("export-json").onclick=()=>save("export_json");$("export-csv").onclick=()=>save("export_csv");$("export-pdf").onclick=()=>save("print_report");
$("load-draft").onclick=async()=>{try{const result=await api("open_draft");if(result)hydrate(result);}catch(e){toast(e.message,true);}};
$("import-csv").onclick=async()=>{try{const result=await api("import_csv");if(result)hydrate({name:result.filename,scope:"partial",components:result.components});}catch(e){toast(e.message,true);}};
document.querySelectorAll("[data-tab]").forEach(button=>button.onclick=()=>{document.querySelectorAll("[data-tab]").forEach(b=>b.classList.toggle("active",b===button));document.querySelectorAll(".tab-panel").forEach(p=>p.classList.toggle("hidden",p.id!=="tab-"+button.dataset.tab));});
rows=[newRow()];renderRows();updateExport();
new QWebChannel(qt.webChannelTransport, channel=>{
  bridge=channel.objects.cos;
  bridge.completed.connect(raw=>{
    let response;try{response=JSON.parse(raw);}catch(e){return toast("앱 응답을 읽지 못했습니다.",true);}
    const callback=pending.get(response.id);if(!callback)return;pending.delete(response.id);
    if(response.ok)callback.resolve(response.result);else callback.reject(new Error(response.error));
  });
  api("info").then(info=>$("app-version").textContent="COS Lab "+info.version).catch(e=>toast(e.message,true));
  cautionOptionsReady=api("caution_options").then(options=>{cautionOptions=options;setCautionSelection(cautionSelection);}).catch(e=>{$("caution-conditions").textContent="주의정보 목록을 불러오지 못했습니다.";toast(e.message,true);});
});
window.runSmokeTest=async()=>{
  if(window.__uiTest)return;
  window.__uiTest={running:true};
  try{
    for(let i=0;i<40&&!bridge;i++)await new Promise(r=>setTimeout(r,100));
    window.__uiTest.stage="structure";
    const candidates=await api("lookup",{query:"글리세린",mode:"name"});
    if(!candidates[0].preview.startsWith("data:image/png"))throw new Error("구조 미리보기 실패");
    const identityInput=(name,smiles)=>({scope:"partial",components:[{component_id:"identity-check",name,canonical_smiles:smiles,amount_pct:20}]});
    const mismatch=await api("validate",identityInput("에탄올","O"));
    if(mismatch.valid||!mismatch.issues.some(item=>item.code==="name_structure_mismatch"))throw new Error("성분명·구조 불일치 차단 실패");
    const equivalent=await api("validate",identityInput("64-17-5","OCC"));
    if(!equivalent.valid)throw new Error("CAS·동일 구조 인식 실패");
    window.__uiTest.stage="inference";
    loadExample();const result=await runAnalysis();
    if(!result||Object.values(result.results).some(r=>r.status!=="complete"))throw new Error("양쪽 모델 예측 실패: "+JSON.stringify(result));
    if(result.validation.identities?.length!==6||result.validation.identities.some(item=>item.status!=="verified"))throw new Error("원료 이름·구조 확인 기록 누락");
    if(document.querySelectorAll(".result-card").length!==2)throw new Error("결과 카드 렌더링 실패");
    if(!result.caution||result.caution.status!=="complete"||document.querySelectorAll(".caution-card").length!==2||!document.querySelector(".caution-item"))throw new Error("주의정보 렌더링 실패: "+JSON.stringify(result.caution).slice(0,300));
    const unmatchedText="사전에 없어서 확인하지 못한 원료: 글리세린, 정제수";
    if($("caution-unmatched").textContent!==unmatchedText||$("caution-unmatched").classList.contains("hidden")||result.caution.unmatched_components.length!==2||result.caution.recognized_component_count!==4)throw new Error("사전 미등록 원료 표시 실패");
    if($("caution-coverage").textContent!=="사전 확인 4개 / 미확인 2개")throw new Error("주의정보 사전 확인 개수 표시 실패");
    window.__uiTest.stage="caution";
    const scoresBefore=JSON.stringify(report.results);
    if(document.querySelectorAll('[data-caution="conditions"]').length!==3||document.querySelectorAll('[data-caution="medications"]').length!==4)throw new Error("관련 주의정보 선택지 필터 실패");
    document.querySelector('[data-caution="medications"][value="tci_topical"]').click();
    await window.cautionReady;
    if(!report||!report.caution.medications.includes("tci_topical")||document.querySelectorAll(".caution-card").length!==3)throw new Error("보고서 화면 주의정보 갱신 실패");
    if(JSON.stringify(report.results)!==scoresBefore||$("export-json").disabled)throw new Error("주의정보 변경이 모델 결과를 바꿨습니다.");
    document.querySelector('[data-caution="medications"][value="tci_topical"]').click();
    await window.cautionReady;
    if(document.querySelectorAll(".caution-card").length!==2)throw new Error("주의정보 선택 해제 실패");
    if($("caution-unmatched").textContent!==unmatchedText)throw new Error("주의정보 선택 시 미확인 원료 표시가 바뀌었습니다.");
    window.__uiTest.stage="auxiliary";
    await window.evidenceReady;
    const auxiliaryIds=Array.from(document.querySelectorAll('.aux-card'),card=>card.dataset.scoreId);
    if(JSON.stringify(auxiliaryIds)!==JSON.stringify(['fragrance_similarity','surfactant_likeness']))throw new Error("두 보조점수 패널 렌더링 실패");
    if(/내분비|농약|Chemical Category|물성 부분|구조 부분/.test($("evidence-body").textContent))throw new Error("이전 보조 모델 표시가 남아 있습니다.");
    if(!document.querySelector(".target-image").src.startsWith("data:image/png"))throw new Error("타깃 구조 렌더링 실패");
    const first=report.input.components[0].component_id;
    if(report.input.components[0].name!=="레티놀"||$("evidence-target").value!==first)throw new Error("시연 예제 기본 타깃 오류");
    await selectEvidence(report.input.components[1].component_id);
    if($("evidence-target").value!==report.input.components[1].component_id)throw new Error("원료 전환 실패");
    if(report.evidence[report.input.components[1].component_id].scores.find(item=>item.model_id==='fragrance_similarity').score!==1)throw new Error("리모넨 시연 점수 오류");
    await selectEvidence(report.input.components[2].component_id);
    const surfactant=report.evidence[report.input.components[2].component_id];
    if(surfactant.scores.find(item=>item.model_id==='surfactant_likeness').score!==1||!surfactant.patterns.some(item=>item.preview))throw new Error("SLS 시연 구조패턴 오류");
    await selectEvidence(first);
    const copy=report;invalidate();if(report!==null||!$("export-json").disabled)throw new Error("이전 결과 무효화 실패");
    report=copy;renderReport();changePage("report");
    window.__uiTest={done:true,ok:true,skin:result.results.skin.score,eye:result.results.eye.score,
      eye_threshold:result.results.eye.threshold,eye_model_sha256:result.results.eye.model_sha256,skin_model_sha256:result.results.skin.model_sha256,
      structure_preview:true,stale_result_cleared:true,cards:2,caution_live_update:true,caution_unmatched:true,identity_verified:true,caution_coverage:true,demo_components:6,demo_default_target:"레티놀",demo_fragrance:true,demo_surfactant_pattern:true,caution_cards:document.querySelectorAll(".caution-card").length,caution_items:document.querySelectorAll(".caution-item").length,auxiliary_cards:2,auxiliary_ids:auxiliaryIds,target_switch:true,
      report_body_px:parseFloat(getComputedStyle(document.querySelector(".result-card .result-label")).fontSize),
      irritation_score_px:parseFloat(getComputedStyle(document.querySelector(".score")).fontSize)};
  }catch(e){window.__uiTest={done:true,ok:false,error:e.message};}
};
