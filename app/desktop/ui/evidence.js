"use strict";
let evidenceRequest = 0;
const numberText = (value, digits=3) => Number.isFinite(value) ? value.toFixed(digits) : "—";

function renderEvidencePanel() {
  if (!report) return;
  report.evidence = Object.fromEntries(Object.entries(report.evidence || {}).filter(([,detail])=>detail.schema_version===2));
  const targets = report.input.components.filter(row=>row.canonical_smiles);
  $("evidence-target").innerHTML=targets.map(row=>'<option value="'+esc(row.component_id)+'">'+esc(row.name||"직접 입력 원료")+' · '+esc(row.amount_pct)+'%</option>').join("");
  const chosen=targets.find(row=>row.component_id===report.evidence_selected_component)||targets.find(row=>row.amount_pct>0)||targets[0];
  if(chosen) window.evidenceReady=selectEvidence(chosen.component_id);
  else $("evidence-body").textContent="참고 정보를 조회할 구조가 없습니다.";
}

async function selectEvidence(id) {
  const owner=report, version=revision, token=++evidenceRequest;
  if(!owner)return;
  const row=owner.input.components.find(item=>item.component_id===id);
  if(!row)return;
  owner.evidence_selected_component=id; $("evidence-target").value=id;
  $("export-pdf").disabled=true;
  if(owner.evidence[id]) {renderTarget(row,owner.evidence[id]);updateExport();return;}
  $("evidence-body").innerHTML='<div class="panel evidence-loading"><span class="spinner"></span><div><strong>'+esc(row.name||"선택 원료")+'의 구조와 보조점수를 계산하고 있습니다.</strong><p>입력한 구조를 로컬에서 분석합니다.</p></div></div>';
  try {
    const result=await api("evidence",{smiles:row.canonical_smiles});
    if(report!==owner||revision!==version)return;
    owner.evidence[id]=result;
    if(token===evidenceRequest)renderTarget(row,result);
  } catch(error) {
    if(report===owner&&revision===version&&token===evidenceRequest) {
      $("evidence-body").innerHTML='<div class="panel evidence-error"><strong>원료 참고 정보를 불러오지 못했습니다.</strong><p>'+esc(error.message)+'</p><button id="retry-evidence" class="button secondary">다시 계산</button></div>';
      $("retry-evidence").onclick=()=>selectEvidence(id);
    }
  } finally {if(report===owner&&token===evidenceRequest)updateExport();}
}

function auxiliaryCard(score) {
  let body;
  if(score.model_id==='fragrance_similarity') {
    body='<h3>'+esc(score.label)+'</h3><div class="aux-value">'+numberText(score.score,4)+'</div>'+
      '<div class="aux-decision">'+(score.score>0?'최근접 참조 · '+esc(score.nearest.name):'모든 참조와 유사도 0')+'</div>'+
      (score.score>0?'<ol class="nearest-matches">'+score.top_matches.map(match=>'<li><span>'+esc(match.name)+'</span><strong>'+numberText(match.tanimoto,4)+'</strong></li>').join('')+'</ol>':'');
  } else {
    const heads=score.matched_head_groups.map(head=>head.label_ko).join(' / ')||'검출 없음';
    const decision=score.status==='held'?'계산 보류':({1:'',0.5:'머리 구조만 검출',0.3:'긴 사슬만 검출',0:'머리 구조·긴 사슬 미검출'}[score.score]);
    body='<h3>'+esc(score.label)+'</h3><div class="aux-value">'+numberText(score.score,4)+'</div>'+(decision?'<div class="aux-decision">'+esc(decision)+'</div>':'')+
      '<p><strong>머리 구조</strong> · '+esc(heads)+'<br><strong>최장 탄소 경로</strong> · '+(score.chain_evaluated?esc(score.longest_aliphatic_chain)+'개 (기준 '+esc(score.min_hydrophobic_chain_length)+'개)':'평가 안 됨')+'</p>'+
      (score.reason?'<p>'+esc(score.reason)+'</p>':'');
  }
  return '<article class="aux-card" data-score-id="'+esc(score.model_id)+'">'+body+'</article>';
}

function essentialNotes(detail) {
  const fragrance=detail.scores.find(score=>score.model_id==='fragrance_similarity');
  const surfactant=detail.scores.find(score=>score.model_id==='surfactant_likeness');
  const notes=[];
  if(fragrance)notes.push(fragrance.score>0&&fragrance.nearest?
    '최근접 향료: '+fragrance.nearest.name+' · 유사도 '+numberText(fragrance.score,4):
    '향료 참조 유사도 '+numberText(fragrance.score,4));
  if(surfactant)notes.push(surfactant.status==='held'?
    '계면활성제 평가 보류: '+surfactant.reason:
    '머리 구조 '+surfactant.matched_head_groups.length+'종 검출 · 최장 탄소 경로 '+surfactant.longest_aliphatic_chain+'개');
  return notes;
}

function renderTarget(row, detail) {
  const p=detail.properties;
  const descriptors=[["분자식",p.formula],["분자량",numberText(p.molecular_weight,2)+" g/mol"],["계산 logP",numberText(p.logp,2)],["극성 표면적",numberText(p.tpsa,2)+" Å²"],["수소결합 주개 / 받개",p.hbd+" / "+p.hba],["방향족 고리",p.aromatic_rings+"개"]];
  const target='<article class="panel target-card"><div class="evidence-kicker">TARGET STRUCTURE</div><h3>'+esc(row.name||"직접 입력 원료")+'</h3><p class="target-amount">입력 함량 '+esc(row.amount_pct)+'%'+(row.amount_pct===0?' · 배합 계산에서 제외':'')+'</p><img class="target-image" src="'+esc(detail.preview)+'" alt="선택한 원료의 타깃 분자 구조"><code class="target-smiles">'+esc(detail.canonical_smiles)+'</code><dl class="descriptor-list">'+descriptors.map(([key,value])=>'<div><dt>'+esc(key)+'</dt><dd>'+esc(value)+'</dd></div>').join('')+'</dl></article>';
  const cards=detail.scores.map(auxiliaryCard).join('');
  const auxiliary='<section class="auxiliary-panel"><h3>보조점수 <span>0–1 · 개별 원료 기준</span></h3><div class="aux-grid">'+cards+'</div></section>';
  const patterns=detail.patterns;
  const gallery=patterns.filter(pattern=>pattern.preview).map(pattern=>'<figure class="pattern-image"><img src="'+esc(pattern.preview)+'" alt="'+esc(pattern.label)+' 매칭 부분 강조"><figcaption><strong>'+esc(pattern.label)+'</strong><span>'+esc(pattern.model_label)+'</span></figcaption></figure>').join('');
  const patternRows=patterns.map(pattern=>'<tr><td>'+esc(pattern.model_label)+'</td><td><strong>'+esc(pattern.label)+'</strong><code>'+esc(pattern.pattern_id)+'</code></td><td>'+esc(pattern.kind)+'</td></tr>').join('');
  const patternPanel='<section class="panel pattern-panel"><h3>구조패턴 주석 <span>'+patterns.length+'건</span></h3>'+(patterns.length?'<div class="pattern-gallery">'+gallery+'</div><div class="table-wrap"><table class="report-table pattern-table"><thead><tr><th>참고 점수</th><th>매칭 패턴</th><th>구분</th></tr></thead><tbody>'+patternRows+'</tbody></table></div>':'<div class="pattern-empty">검출된 구조 없음</div>')+'</section>';
  const summary='<section class="panel annotation-panel"><h3>주석 요약</h3><div class="local-annotations"><ul>'+essentialNotes(detail).map(note=>'<li>'+esc(note)+'</li>').join('')+'</ul></div><details class="pubchem-section"><summary>문헌 원문 보기</summary><div class="pubchem-heading"><h4>PubChem</h4><button id="load-annotations" class="button secondary">원문 조회</button></div><p class="source-note">조회 시 선택 원료의 SMILES를 PubChem에 전송합니다.</p><div id="pubchem-annotations"></div></details></section>';
  const source='<details class="evidence-source"><summary>계산 출처</summary><div><span>제공된 similarity 자료</span><span>RDKit '+esc(detail.source.rdkit)+'</span><code>SHA-256 '+esc(detail.source.sha256)+'</code></div></details>';
  $("evidence-body").innerHTML='<div class="target-grid">'+target+auxiliary+'</div>'+patternPanel+summary+source;
  renderAnnotations(detail.annotations);
  $("load-annotations").onclick=()=>loadAnnotations(row,detail);
}

function renderAnnotations(value) {
  if(!value) {$("pubchem-annotations").innerHTML='';return;}
  const entries=value.entries||[];
  $("pubchem-annotations").innerHTML=(!entries.length?'<p class="annotation-status">'+esc(value.note)+'</p>':'')+(value.cid?'<p><a href="'+esc(value.source_url)+'">PubChem CID '+value.cid+' · '+esc(value.title)+'</a></p>':'')+entries.map(item=>'<blockquote><p>'+esc(item.text)+'</p><cite>'+esc(item.source)+' · <a href="'+esc(item.url)+'">원출처</a></cite></blockquote>').join('')+(value.fetched_at?'<p class="source-note">조회 시각 '+esc(new Date(value.fetched_at).toLocaleString('ko-KR'))+'</p>':'');
}

async function loadAnnotations(row,detail) {
  const owner=report, version=revision;
  const button=$("load-annotations");button.disabled=true;button.textContent='조회 중…';
  try {
    const result=await api('annotations',{smiles:detail.canonical_smiles});
    if(report!==owner||revision!==version)return;
    detail.annotations=result;
    if(owner.evidence_selected_component===row.component_id)renderAnnotations(result);
  } catch(error) {
    if(report===owner&&owner.evidence_selected_component===row.component_id)toast(error.message,true);
  } finally {if(document.contains(button)){button.disabled=false;button.textContent='원문 조회';}}
}
$("evidence-target").onchange=()=>{window.evidenceReady=selectEvidence($("evidence-target").value);};
