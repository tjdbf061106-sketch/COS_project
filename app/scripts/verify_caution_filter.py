"""Exercise ingredient-dependent choices in the real Qt UI and literature bridge."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_app import QApplication, Window, Qt, QTimer

OUTPUT = ROOT / "build/caution-filter"
OUTPUT.mkdir(parents=True, exist_ok=True)
SCRIPT = r"""
(async()=>{
  const check=(ok,message)=>{if(!ok)throw new Error(message);};
  for(let i=0;i<100&&!cautionOptions;i++)await new Promise(resolve=>setTimeout(resolve,50));
  check(!!cautionOptions,'Options unavailable');
  // No inference is needed to test choice filtering. These fixtures display held scores.
  renderEvidencePanel=()=>{window.evidenceReady=Promise.resolve();};
  const fixture=(name,components)=>({app_version:'0.3.0',created_at:new Date().toISOString(),input_hash:'choice-test',
    input:{name,scope:'partial',components:components.map(([name,canonical_smiles,amount_pct],i)=>({component_id:String(i),name,canonical_smiles,amount_pct}))},
    validation:{total:components.reduce((n,row)=>n+row[2],0),unlisted:100-components.reduce((n,row)=>n+row[2],0),warnings:[]},
    weights:[],results:{skin:{status:'held',reasons:['선택지 표시 검사']},eye:{status:'held',reasons:['선택지 표시 검사']}}});
  const sls=['Sodium lauryl sulfate','CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]',1];
  // Use the actual PubChem reference (CID 3014024), not an arbitrary chain homologue.
  const bak=['Benzalkonium chloride','CCCCCCCCCCCCC[N+](C)(C)Cc1ccccc1.[Cl-]',.01];
  const glycerin=['Glycerin','OCC(O)CO',100];
  const eyeConditions=['dry_eye_disease','glaucoma_chronic_drops','allergic_conjunctivitis_cl_wearer'];
  const cases=[
    ['salicylic',[['Salicylic acid','O=C(O)c1ccccc1O',2]],[],['isotretinoin_oral']],
    ['glycerin',[glycerin],[],[],['Glycerin']],
    ['sls',[sls],['atopic_dermatitis','contact_dermatitis_history'],['tci_topical']],
    ['bak',[bak],eyeConditions,['prostaglandin_analog_drops','soft_contact_lens_wear']],
    ['ethanol-15',[['Ethanol','CCO',15]],[],['isotretinoin_oral','tci_topical']],
    ['ethanol-20',[['Ethanol','CCO',20]],['atopic_dermatitis'],['isotretinoin_oral','tci_topical']],
    ['zero-sls',[[sls[0],sls[1],0],glycerin],[],[],['Glycerin']],
    ['unregistered',[['직접 입력 원료','CCC',20]],[],[],['CCC']],
    ['registered-structure',[['직접 입력 원료','OCC',20]],['atopic_dermatitis'],['isotretinoin_oral','tci_topical']],
    ['mixture',[sls,bak],['atopic_dermatitis','contact_dermatitis_history',...eyeConditions],['tci_topical','prostaglandin_analog_drops','soft_contact_lens_wear']],
    ['mixed-coverage',[sls,['글리세린','OCC(O)CO',5]],['atopic_dermatitis','contact_dermatitis_history'],['tci_topical'],['글리세린']],
    ['zero-unregistered',[sls,['미등록 원료','CCC',0]],['atopic_dermatitis','contact_dermatitis_history'],['tci_topical']],
    ['duplicate-unregistered',[['직접 입력 원료','CCC',10],['직접 입력 원료','CCC',10]],[],[],['CCC']],
    ['direct-smiles',[['직접 입력 원료','CCCO',1]],[],[],['CCCO']],
    ['cas-ethanol',[['64-17-5','OCC',20]],['atopic_dermatitis'],['isotretinoin_oral','tci_topical']],
    ['sls-alias',[['SLS','[Na+].CCCCCCCCCCCCOS([O-])(=O)=O',1]],['atopic_dermatitis','contact_dermatitis_history'],['tci_topical']]
  ];
  const visible=kind=>Array.from(document.querySelectorAll('[data-caution="'+kind+'"]'),e=>e.value).sort();
  const equal=(a,b)=>JSON.stringify([...a].sort())===JSON.stringify([...b].sort());
  const originalApi=api, actions=[];
  api=(action,data)=>{actions.push(action);return originalApi(action,data);};
  const checks=[];
  for(const [name,components,conditions,medications,unmatched=[]] of cases){
    setCautionSelection({conditions:['atopic_dermatitis'],medications:['prostaglandin_analog_drops']});
    report=fixture(name,components);renderReport();changePage('report');
    check($('export-json').disabled,name+': exports must wait for matching');
    check($('caution-coverage').classList.contains('hidden'),name+': old counts during loading');
    await window.cautionReady;
    check(report.caution.status!=='held',name+': '+JSON.stringify(report.caution.reasons));
    const coverageText=unmatched.length?'사전에 없어서 확인하지 못한 원료: '+unmatched.join(', '):'';
    check($('caution-unmatched').textContent===coverageText,name+': unregistered ingredient names');
    check($('caution-unmatched').classList.contains('hidden')===!unmatched.length,name+': coverage visibility');
    check(!$('caution-unmatched').querySelector('img'),name+': ingredient name interpreted as HTML');
    check(equal([...new Set(report.caution.unmatched_components.map(item=>item.display_name))],unmatched),name+': report coverage');
    const unknownCount=name==='duplicate-unregistered'?2:unmatched.length;
    const knownCount=components.filter(row=>row[2]>0).length-unknownCount;
    check($('caution-coverage').textContent==='사전 확인 '+knownCount+'개 / 미확인 '+unknownCount+'개',name+': coverage counts');
    check(equal(visible('conditions'),conditions),name+': condition filter');
    check(equal(visible('medications'),medications),name+': medication filter');
    check(cautionSelection.conditions.every(id=>conditions.includes(id))&&cautionSelection.medications.every(id=>medications.includes(id)),name+': hidden selections persisted');
    check(!document.querySelector('.caution-card.clear'),name+': unrelated result card');
    const before=JSON.stringify(report.results), calls=actions.length;
    while(document.querySelector('[data-caution]:not(:checked)')){document.querySelector('[data-caution]:not(:checked)').click();await window.cautionReady;}
    check(actions.length===calls,name+': selection re-ran a backend request');
    check(before===JSON.stringify(report.results),name+': model results changed');
    check($('caution-unmatched').textContent===coverageText,name+': selection changed coverage');
    check(equal(Object.keys(report.caution.results),conditions)&&equal(Object.keys(report.caution.medication_results),medications),name+': export scope');
    check(document.querySelectorAll('.caution-card').length===conditions.length+medications.length,name+': card count');
    check(!conditions.length===document.querySelector('#caution-conditions').closest('.caution-group').classList.contains('hidden'),name+': condition group visibility');
    if(!conditions.length&&!medications.length){
      check($('caution-picker').classList.contains('hidden'),name+': empty picker');
      check(report.caution.recognized_component_count===0?!$('caution-body').textContent.includes('없습니다'):$('caution-body').textContent.includes('매칭된 주의정보가 없습니다'),name+': empty state');
    }
    checks.push({name,conditions,medications,unmatched,passed:true});
  }
  // A delayed response from the previous report cannot restore obsolete choices.
  let releaseOld;const gate=new Promise(resolve=>releaseOld=resolve);
  api=(action,data)=>{const response=originalApi(action,data);return action==='caution'&&data.input.name==='race-old'?response.then(value=>gate.then(()=>value)):response;};
  report=fixture('race-old',[sls]);renderReport();const oldReady=window.cautionReady;
  report=fixture('race-new',[glycerin]);renderReport();await window.cautionReady;
  releaseOld();await oldReady;
  check(report.input.name==='race-new'&&visible('conditions').length===0&&visible('medications').length===0,'Stale response changed current choices');
  check($('caution-unmatched').textContent==='사전에 없어서 확인하지 못한 원료: Glycerin','Stale response changed coverage');
  // Failure must stay distinguishable from no matches and support retry.
  api=(action,data)=>action==='caution'?Promise.reject(new Error('연결 확인 테스트')):originalApi(action,data);
  report=fixture('failure',[sls]);renderReport();await window.cautionReady;
  check(report.caution.status==='held'&&!!$('retry-caution'),'Failure was reported as no match');
  check($('caution-unmatched').classList.contains('hidden'),'Failure kept old unregistered names');
  check($('caution-coverage').classList.contains('hidden'),'Failure kept old counts');
  api=originalApi;$('retry-caution').click();await window.cautionReady;
  check(equal(visible('conditions'),['atopic_dermatitis','contact_dermatitis_history']),'Retry did not restore related choices');
  setCautionSelection({conditions:[],medications:[]});await refreshCaution();
  const bad=fixture('이름 구조 불일치',[['에탄올','O',20]]).input;
  const invalid=await originalApi('validate',bad);
  check(!invalid.valid&&invalid.issues.some(item=>item.code==='name_structure_mismatch'),'Mismatched imported ingredient accepted');
  hydrate(bad);
  const blocked=await runAnalysis();
  check(!blocked&&!$('issues').classList.contains('hidden')&&$('issues').textContent.includes('일치하지'),'Mismatch did not show input guidance');
  check(report===null&&$('export-json').disabled,'Mismatch kept an old export');
  changePage('report');
  report=fixture('사전 등록 여부 확인',[sls,['글리세린','OCC(O)CO',5],['나이아신아마이드','NC(=O)c1cccnc1',2]]);
  renderReport();await window.cautionReady;
  check(report.caution.status==='not_selected'&&!$('caution-unmatched').classList.contains('hidden'),'Coverage requires selection');
  $('caution-panel').scrollIntoView();
  check(!actions.includes('analyze'),'Filtering invoked inference');
  window.__filterResult={done:true,passed:true,cases:checks,stale_response:true,retry:true};
})().catch(error=>{window.__filterResult={done:true,passed:false,error:error.message,stack:error.stack};});
"""

QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
app = QApplication(["Caution choices check"])
window = Window()
window.show()
QTimer.singleShot(180000, lambda: app.exit(2))
timer = QTimer(window)
timer.setInterval(250)

def inspect(value):
    if not value:
        return
    result = json.loads(value)
    if not result or not result.get("done"):
        return
    timer.stop()
    (OUTPUT / "filter-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    def finish():
        window.grab().save(str(OUTPUT / "filtered-options.png"))
        if result["passed"]:
            window.print_pdf(OUTPUT / "unregistered-ingredients.pdf")
        else:
            complete(False)

    def complete(success):
        result["pdf_created"] = bool(success)
        result["passed"] = result["passed"] and bool(success)
        (OUTPUT / "filter-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True), flush=True)
        app.exit(0 if result["passed"] else 1)
    window.view.page().pdfPrintingFinished.connect(lambda path, success: complete(success))
    QTimer.singleShot(700, finish)

timer.timeout.connect(lambda: window.view.page().runJavaScript("JSON.stringify(window.__filterResult||null)", inspect))
def loaded(ok):
    if not ok:
        app.exit(1)
        return
    window.view.page().runJavaScript(SCRIPT)
    timer.start()
window.view.loadFinished.connect(loaded)
raise SystemExit(app.exec())
