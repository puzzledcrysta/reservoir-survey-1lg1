import {query, readInput, encodeInput} from './api.js';
import {el, evidence, table} from './table.js';

const byId = id => document.getElementById(id);
const settings = JSON.parse(byId('settings').textContent);
const links = [...document.querySelectorAll('[data-module]')];
const body = byId('grid-data');
const alert = byId('notice');
const live = byId('state');
const action = document.querySelector('#source button[type=submit]');
const topExport = byId('export');
let selected = Object.hasOwn(settings.tabs, location.hash.slice(1)) ? location.hash.slice(1) : 'domain';
let result = null;
let inputs = {};
let reviewVersion = 0;
let mergeVersion = 0;
let mergeReport = null;
let renderEpoch = 0;
const uploaded = new Map();

const MERGE_STATUS = {EFFECTIVE: '原结论有效', PARTIAL: '部分调整', REPLACED: '已被取代'};
const BOUNDARY_STATUS = {SINGLE: '单源', OVERLAP: '重叠·补测优先', GAP: '里程空档'};

function notice(message, error = false) {
  alert.value = message;
  alert.classList.toggle('problem', error);
}

function tag(code) {
  return el('span', settings.reasons[code] || code, code === 'MATCH' ? 'state' : 'state problem');
}


function showEvidence(row) {
  const panel = byId('evidence-panel');
  const record = byId('evidence-key');
  const details = byId('signal');
  if (!row) {
    record.textContent = '';
    details.replaceChildren(el('p', '本批没有可采信记录', 'empty'));
    return;
  }
  record.textContent = row.key;
  const scale = new Map();
  for (const item of row.proof) {
    const magnitude = Math.abs(Number(item.value));
    if (Number.isFinite(magnitude)) scale.set(item.unit, Math.max(scale.get(item.unit) || 0, magnitude));
  }
  const content = el('dl', undefined, panel.dataset.instrument);
  for (const item of row.proof) {
    const measure = el('dt', item.metric);
    measure.append(el('output', item.unit ? `${item.value} ${item.unit}` : item.value));
    const value = el('dd');
    const magnitude = Math.abs(Number(item.value));
    const max = scale.get(item.unit);
    if (Number.isFinite(magnitude) && max) {
      const meter = el('span', undefined, 'track');
      meter.style.setProperty('--range', `${100 * magnitude / max}%`);
      meter.setAttribute('aria-hidden', 'true');
      value.append(meter);
    }
    content.append(measure, value);
  }
  details.replaceChildren(content);
}

function inspect(row) {
  const button = el('button', '查看依据', 'btn');
  button.type = 'button';
  button.addEventListener('click', () => showEvidence(row));
  const raw = evidence('原始字段', row.raw);
  const cell = el('div');
  cell.append(button, raw);
  return cell;
}

function setRun(report) {
  result = report;
  byId('created').textContent = `${report.manifest.created.slice(0, 19).replace('T', ' ')} UTC`;
  showEvidence(report.accepted[0]);
  const id = result.manifest.run_id;
  byId('run-id').textContent = id.slice(0, 9);
  byId('run-id').title = id;
  topExport.hidden = false;
  topExport.href = `/api/export/${id}`;
  const values = {...result.counts, delta: result.book.delta, mismatched: result.book.mismatched};
  for (const cell of document.querySelectorAll('[data-count]')) cell.textContent = values[cell.dataset.count];
  live.textContent = `批次 ${id.slice(0, 9)} · ${result.balanced ? '记录已对齐' : '记录数不符'}`;
}

async function render() {
  const ticket = ++renderEpoch;
  const stage = selected;
  byId('phase').textContent = settings.tabs[stage];
  byId('review').hidden = true;
  byId('merge').hidden = stage !== 'merge';
  if (stage !== 'merge' && result) topExport.href = `/api/export/${result.manifest.run_id}`;
  for (const link of links) {
    if (link.dataset.module === stage) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  if (!result) return;
  const id = result.manifest.run_id;
  const raw = row => evidence('来源字段', row.raw);
  const key = ['业务键', 'key'];
  const line = ['行号', 'line', 'num'];
  try {
    let view, rows;
    if (stage === 'domain') {
      view = [key, [`复算值 · ${settings.unit}`, 'amount', 'num'], line, ['明细依据', inspect]];
      rows = result.accepted;
    } else if (stage === 'quality') {
      view = [key, line, ['判定', row => tag(row.code)], ['说明', 'detail'], ['字段', raw]];
      rows = [...result.quarantine, ...result.suppressed].sort((a,b) => a.line-b.line);
    } else if (stage === 'reconcile') {
      view = [key, ['实际', 'amount', 'num'], ['外部账', 'reference', 'num'], ['差值', 'delta', 'num'], ['外部行', 'book_line', 'num'], ['结论', row => tag(row.code)]];
      rows = [...result.book.rows].sort((a,b) => Number(a.code === 'MATCH') - Number(b.code === 'MATCH'));
    } else if (stage === 'intake') {
      const intake = await query('/api/intake', inputs);
      view = [line, ['分类', 'kind'], ['字段', raw]];
      rows = [...intake.rows.map(row => ({...row,kind:'完整记录'})), ...intake.rejected.map(row => ({...row,kind:'坏行'})),
              ...intake.blank_lines.map(line => ({line,kind:'空白行',raw:[]})),
              ...intake.header_lines.map(line => ({line,kind:'重复表头',raw:[]}))].sort((a,b) => a.line-b.line);
    } else if (stage === 'contract') {
      const contract = await query('/api/contract', inputs);
      view = [key, line, ['修订', 'revision', 'num'], ['来源时刻 UTC', 'time'], ['字段', row => evidence('归一值', Object.entries(row.fields).map(([k,v]) => `${k} · ${v}`))]];
      rows = contract.accepted;
    } else if (stage === 'runs') {
      const runs = await query('/api/runs');
      view = [['指纹','id'], ['创建 UTC','created'], ['操作', row => {
        const current = row.id === id;
        const button = el('button',current ? '复算当前批' : '打开此批','btn');
        button.addEventListener('click', async () => {
          button.disabled = true;
          try {
            if (current) {
              setRun(await query(`/api/runs/${id}/replay`, {}));
              notice('复算已核对');
            } else {
              const [past, original] = await Promise.all([
                query(`/api/runs/${row.id}`), query(`/api/runs/${row.id}/source`),
              ]);
              inputs = original;
              setRun(past);
              notice('已打开历史批次');
              await render();
            }
          }
          catch (error) { notice(error.message, true); }
          finally { button.disabled = false; }
        });
        return button;
      }]];
      rows = runs;
    } else if (stage === 'merge') {
      await renderMerge(id, ticket);
      return;
    } else {
      const timeline = await query(`/api/review/${id}`);
      view = [['版本','version','num'], ['结论','decision'], ['复核意见','note'], ['登记 UTC','changed']];
      rows = timeline;
      if (ticket === renderEpoch) {
        reviewVersion = timeline[0]?.version || 0;
        byId('review').hidden = false;
      }
    }
    if (ticket === renderEpoch) table(body, view, rows);
  } catch (error) {
    if (ticket === renderEpoch) notice(error.message, true);
  }
}

window.addEventListener('hashchange', () => {
  selected = Object.hasOwn(settings.tabs, location.hash.slice(1)) ? location.hash.slice(1) : 'domain';
  render();
});

function mergePicker(runs, currentId) {
  const select = el('select');
  select.append(new Option('（不参与）', ''));
  for (const row of runs) {
    const option = new Option(`${row.id.slice(0, 9)} · ${row.created.slice(0, 19)}`, row.id);
    if (row.id === currentId) option.selected = true;
    select.append(option);
  }
  return select;
}

async function renderMerge(currentId, ticket) {
  const runs = await query('/api/runs');
  const old = byId('merge-pickers');
  if (old) old.remove();
  const pickers = el('div');
  pickers.id = 'merge-pickers';
  // 基线固定为当前批，补测从历史批次中选择；按提交顺序确定权威优先级
  const base = mergePicker(runs, currentId);
  base.disabled = true;
  const supplement = mergePicker(runs, runs.find(row => row.id !== currentId)?.id || '');
  pickers.append(el('label', '基线批次'), base, el('label', '补测批次（重叠区权威）'), supplement);
  byId('merge').prepend(pickers);
  byId('merge').dataset.base = currentId;
  supplement.addEventListener('change', () => { byId('merge').dataset.supplement = supplement.value; });
  byId('merge').dataset.supplement = supplement.value;

  const history = await query('/api/merges');
  const columns = [
    ['合卷指纹', row => row.id.slice(0, 9)],
    ['定版 UTC', 'created'],
    ['状态', 'status'],
    ['打开', row => {
      const button = el('button', '查看合卷', 'btn');
      button.addEventListener('click', async () => {
        try { await showMerge(await query(`/api/merges/${row.id}`), ticket); }
        catch (error) { notice(error.message, true); }
      });
      return button;
    }],
  ];
  const parts = [el('h3', '已定版合卷（工作台与导出同版）'), ];
  const wrap = el('div');
  table(wrap, columns, history);
  parts.push(wrap);
  if (ticket === renderEpoch) body.replaceChildren(...parts);
}

async function showMerge(report, ticket) {
  mergeReport = report;
  const totals = report.totals;
  byId('merge-totals').value =
    `调整前 ${totals.original_total} → 调整后 ${totals.merged_total} ${settings.unit} · ` +
    `去重 ${totals.removed_overlap} · 差额 ${totals.delta} · 闭合残差 ${totals.closure_residual}`;
  topExport.hidden = false;
  topExport.href = `/api/export/merge/${report.merge_id}`;

  const adjustmentView = [
    ['角色', 'role'], ['测段', 'key'], ['行号', 'line', 'num'],
    ['里程', row => `${row.span_from}–${row.span_to}`],
    ['原结论', 'original_amount', 'num'],
    ['保留计入', 'retained_amount', 'num'],
    ['重叠去重', 'removed_amount', 'num'],
    ['结论状态', row => el('span', MERGE_STATUS[row.status] || row.status,
                           row.status === 'EFFECTIVE' ? 'state' : 'state problem')],
    ['责任去向', row => row.removed_by.map(item => `${item.run_id.slice(0, 9)} 取 ${item.amount}`).join('；') || '—'],
  ];
  const boundaryView = [
    ['里程起', 'from', 'num'], ['里程止', 'to', 'num'],
    ['边界状态', row => el('span', BOUNDARY_STATUS[row.status] || row.status,
                           row.status === 'OVERLAP' ? 'state problem' : 'state')],
    ['归属测段', 'owner_key'], ['挖方', 'cut', 'num'], ['填方', 'fill', 'num'],
  ];
  const head = el('h3', `合卷 ${report.merge_id.slice(0, 9)} · 边界调整单与逐区间归属`);
  const note = el('p', `并集里程 ${totals.union_mileage} 米；重叠 ${totals.overlap_mileage} 米；` +
                       `空档 ${totals.gap_mileage} 米（空档不臆造断面）`, 'empty');
  const aWrap = el('div');
  table(aWrap, adjustmentView, report.adjustments);
  const bWrap = el('div');
  table(bWrap, boundaryView, report.boundaries);
  if (ticket !== renderEpoch) return;
  body.replaceChildren(head, note, el('h4', '测段责任（哪些结论已变 / 仍有效）'), aWrap,
                       el('h4', '合卷边界（每区间仅一个权威来源）'), bWrap);

  const timeline = await query(`/api/review/merge/${report.merge_id}`);
  mergeVersion = timeline[0]?.version || 0;
  const tWrap = el('div');
  table(tWrap, [['版本','version','num'], ['结论','decision'], ['复核意见','note'], ['登记 UTC','changed']], timeline);
  const reviewBox = el('div');
  const opinion = el('textarea');
  opinion.maxLength = 500;
  const decision = el('select');
  decision.append(new Option('确认'), new Option('退回'));
  const submit = el('button', '提交合卷复核', 'btn btn--primary');
  submit.type = 'button';
  submit.addEventListener('click', async () => {
    try {
      await query(`/api/review/merge/${report.merge_id}`,
                  {version: mergeVersion, decision: decision.value, note: opinion.value});
      notice('合卷复核已登记');
      opinion.value = '';
      await showMerge(await query(`/api/merges/${report.merge_id}`), ticket);
    } catch (error) { notice(error.message, true); }
  });
  reviewBox.append(el('h4', '合卷复核（独立版本链，旧版本提交返回 409）'), tWrap,
                   el('label', '复核意见（有边界调整时必填）'), opinion, decision, submit);
  if (ticket === renderEpoch) body.append(reviewBox);
}

byId('merge').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.target;
  const supplementId = form.dataset.supplement;
  if (!supplementId) return notice('请选择补测批次', true);
  try {
    const report = await query('/api/merges', {
      run_ids: [form.dataset.base, supplementId], roles: ['基线', '补测']});
    notice(report.reused ? '命中已定版合卷，未重复累加' : '合卷已定版');
    await showMerge(report, renderEpoch);
  } catch (error) { notice(error.message, true); }
});
byId('sample').addEventListener('click', async () => {
  const paths = ['shift', 'external'];
  try {
    const responses = await Promise.all(paths.map(name => fetch(`/api/samples/${name}`)));
    if (responses.some(item => !item.ok)) throw Error('样例暂时不可用');
    const files = await Promise.all(responses.map(item => item.arrayBuffer()));
    for (const [index,name] of ['source','book'].entries()) {
      const decoded = new TextDecoder('utf-8').decode(files[index]);
      byId(`${name}-csv`).value = decoded;
      uploaded.set(name,{text:byId(`${name}-csv`).value,bytes:files[index]});
    }
    byId('source-file').value = '';
    byId('book-file').value = '';
    document.querySelector('#source details').open = true;
    notice('样例已载入');
  } catch (error) { notice(error.message, true); }
});
for (const name of ['source','book']) {
  byId(`${name}-file`).addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    action.disabled = true;
    try {
      const [text,bytes] = await readInput(file);
      byId(`${name}-csv`).value = text;
      uploaded.set(name,{text:byId(`${name}-csv`).value,bytes});
      notice(`已读取 ${file.name}`);
    } catch (error) {
      event.target.value = '';
      notice(error.message, true);
    } finally { action.disabled = false; }
  });
}
byId('source').addEventListener('submit', async event => {
  event.preventDefault();
  const candidate = {};
  for (const [control,name] of [['source','data'],['book','book']]) {
    const text = byId(`${control}-csv`).value;
    const original = uploaded.get(control);
    if (original && text === original.text) candidate[`${name}_base64`] = encodeInput(original.bytes);
    else if (text.length || original) candidate[name] = text;
  }
  action.disabled = true;
  ++renderEpoch;
  notice('计算中');
  try {
    const report = await query('/api/runs', candidate);
    inputs = candidate;
    setRun(report);
    notice('批次已计算');
    await render();
  } catch (error) { notice(error.message, true); }
  finally { action.disabled = false; }
});
byId('review').addEventListener('submit', async event => {
  event.preventDefault();
  const id = result.manifest.run_id;
  const note = byId('review-note');
  try {
    await query(`/api/review/${id}`, {version: reviewVersion, decision: byId('decision').value, note: note.value});
    notice('复核已登记');
    note.value = '';
    await render();
  } catch (error) { notice(error.message, true); }
});
render();
