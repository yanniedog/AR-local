"""Standalone searchable inventory; bank-supplied content is text, never HTML."""
import json


def write_html(path, report, products):
    payload = json.dumps({'report': report, 'products': products}, ensure_ascii=False)
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AR product coverage inventory</title>
<style>
body{font:16px/1.5 system-ui,sans-serif;color:#e8eef8;background:#101724;margin:0;padding:24px;max-width:1450px;margin:auto}
h1{font-size:30px;margin:0}h2{font-size:21px}p{max-width:100ch;color:#becbdd}
.notice{border-left:4px solid #eac278;padding:12px 18px;background:#202c3e}
.controls{display:flex;gap:12px;flex-wrap:wrap;position:sticky;top:0;background:#101724;padding:15px 0}
input,select,button{font:inherit;color:inherit;background:#202c3e;border:1px solid #526078;border-radius:6px;padding:8px;box-sizing:border-box;max-width:100%;min-height:48px}
input{flex:1;min-width:min(230px,100%)}select{min-width:0}a{color:#89cafa}table{border-collapse:collapse;width:100%;font-size:14px}
td,th{border-bottom:1px solid #39465a;padding:9px;text-align:left;vertical-align:top}th{color:#a4b9d4}
details{background:#182234;border:1px solid #39465a;padding:14px;border-radius:7px;margin:10px 0}
summary{cursor:pointer;font-weight:600}.meta{color:#acbad1;font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 ui-monospace,monospace}
.tablewrap{overflow:auto}.chips{display:flex;gap:12px;flex-wrap:wrap}.chip{background:#223148;padding:12px 18px;border-radius:8px}.chip strong{display:block;font-size:24px}
</style><h1>AR product coverage inventory</h1><p id="asof"></p>
<div class="notice">This report lists the fields actually delivered to AR-app. The baseline does not contain a complete document archive or verified executable terms. Missing fees and criteria remain unknown.</div>
<div class="chips" id="counts"></div>
<p>Download: <a href="banks.csv">Banks</a> · <a href="products.csv">Products</a> · <a href="rates.csv">All rate rows</a> · <a href="product-parameters.csv">Every product parameter</a> · <a href="fields.csv">Field coverage</a> · <a href="historical-metrics.csv">Historical metrics</a> · <a href="audit-evidence.json">Evidence and counts</a> · <a href="product-data.json">Original product values</a></p>
<details><summary>Coverage, source counts and historical gaps</summary><pre id="coverage"></pre></details>
<p id="history-downloads" hidden>Full history: <a href="historical-dates.csv">Every selected date</a> · <a href="historical-banks.csv">Every observed bank</a> · <a href="historical-products.csv">Every bank/product/date</a> · <a href="historical-parameter-changes.csv.gz">Granular observed parameter changes (compressed CSV)</a> · <a href="historical-audit.json">Dated asset evidence</a></p>
<p id="metrics-download" hidden><a href="reported-metrics.md">Metric definitions, formulas, units and limitations</a></p>
<details><summary>All banks and reported fields</summary><div class="tablewrap" id="banks"></div><h2>Field presence</h2><div class="tablewrap" id="fields"></div><h2>Historical population</h2><div class="tablewrap" id="historical-banks"></div></details>
<h2>Products and complete reported parameters</h2>
<div class="controls"><input id="search" aria-label="Search bank, product or fine print" placeholder="Search bank, product or fine print"><select id="bank" aria-label="Bank"><option value="">All banks</option></select><select id="section" aria-label="Product family"><option value="">All product families</option><option>Mortgage</option><option>Savings</option><option>TD</option><option value="unclassified">Other / unclassified</option></select></div>
<p id="matched" role="status"></p><div id="products"></div><button id="more">Show 100 more</button>
<script type="application/json" id="data">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),r=data.report;
const byId=id=>document.getElementById(id),element=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e};
byId('asof').textContent='Observation '+r.run_date+' · '+r.source_manifest.tag+' · Generated '+r.generated_at;
for(const [label,value] of [['Products in details',r.published_counts.products_in_details],['Products with rates',r.published_counts.products_with_rates],['Published rate rows',r.published_counts.rate_rows],['Reported fees',r.published_counts.fees]]){const c=element('div',label);c.className='chip';c.prepend(element('strong',String(value)));byId('counts').append(c)}
byId('coverage').textContent=JSON.stringify({source_counts:r.source_counts,published_counts:r.published_counts,historical_coverage:r.historical_coverage,coverage:r.coverage,limitations:r.limitations},null,2);
function table(rows,columns){const t=element('table'),h=element('tr');columns.forEach(c=>h.append(element('th',c)));t.append(h);for(const row of rows){const tr=element('tr');columns.forEach(c=>tr.append(element('td',typeof row[c]==='object'?JSON.stringify(row[c]):String(row[c]??''))));t.append(tr)}return t}
byId('banks').append(table(r.banks,['provider','products_in_details_or_rates','products_with_rates','published_rate_rows','fees_entries','features_entries','eligibility_entries','constraints_entries','failure_records','document_completeness']));
byId('fields').append(table(r.fields,['record_type','field','present_records','denominator']));
byId('history-downloads').hidden=!r.historical_banks;byId('metrics-download').hidden=!r.metrics_dictionary;
if(r.historical_banks)byId('historical-banks').append(table(r.historical_banks,['provider','observed_dates','first_observed_date','last_observed_date','distinct_product_keys','product_section_days','rate_row_observations','absence_meaning']));
for(const bank of r.banks){const o=element('option',bank.provider);o.value=bank.provider;byId('bank').append(o)}
const indexed=data.products.map(p=>({p,search:JSON.stringify(p).toLowerCase()}));let limit=100;
function reportFamilies(summary){return summary.product_families??summary.sections}
function matchesFamily(summary,selected){const families=reportFamilies(summary);return !selected||(selected==='unclassified'?!families:families.split('|').includes(selected))}
function draw(){const q=byId('search').value.trim().toLowerCase(),bank=byId('bank').value,section=byId('section').value;const hits=indexed.filter(x=>(!q||x.search.includes(q))&&(!bank||x.p.summary.provider===bank)&&matchesFamily(x.p.summary,section));byId('products').replaceChildren();byId('matched').textContent=hits.length+' matched · showing '+Math.min(limit,hits.length);byId('more').hidden=hits.length<=limit;for(const {p} of hits.slice(0,limit)){const d=element('details'),s=p.summary;d.append(element('summary',s.provider+' — '+s.product_name));const m=element('p',(reportFamilies(s)||'Unclassified')+' · '+s.published_rate_rows+' rate rows · '+s.fees_entries+' fees · '+s.eligibility_entries+' criteria');m.className='meta';d.append(m);let loaded=false;d.addEventListener('toggle',()=>{if(!d.open||loaded)return;loaded=true;d.append(element('p','Document completeness: unknown. Published source fields follow without truncation.'));for(const [name,value] of Object.entries(p.detail||{})){const g=element('details');g.append(element('summary',name));g.append(element('pre',typeof value==='string'?value:JSON.stringify(value,null,2)));d.append(g)}const g=element('details');g.append(element('summary','All published rate rows'));g.append(element('pre',JSON.stringify(p.rates,null,2)));d.append(g)});byId('products').append(d)}}
for(const id of ['search','bank','section'])byId(id).addEventListener('input',()=>{limit=100;draw()});byId('more').addEventListener('click',()=>{limit+=100;draw()});draw();
</script></html>'''
    if report.get('terms_evidence'):
        template = template.replace('for(const [name,value]', "if(p.terms_evidence){const evidence=element('details');evidence.append(element('summary','Selected observation evidence · '+p.terms_evidence.evidence_class));evidence.append(element('pre',JSON.stringify(p.terms_evidence,null,2)));d.append(evidence)}" + 'for(const [name,value]')
    path.write_text(template.replace('__DATA__', payload), encoding='utf-8')
