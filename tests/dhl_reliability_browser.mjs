// Real local financial APIs only. Start serve_dhl_reliability_fixture.py and Vite on 8067 first.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const f=JSON.parse(fs.readFileSync(process.env.DHL_RELIABILITY_FIXTURE_JSON||'/private/tmp/smithsons-reliability-http-fixture.json'));
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE));
console.log('Launching browser');
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH});
const ctx=await browser.newContext({acceptDownloads:true});ctx.setDefaultTimeout(120000);
await ctx.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
await ctx.addInitScript(token=>localStorage.setItem('token',token),f.token);
const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
const state=async()=>{const r=await ctx.request.get('http://127.0.0.1:8071/dhl-reports/monthly-payouts/2026-09-01',{headers:{Authorization:'Bearer '+f.token}});assert.equal(r.status(),200);return r.json();};
try {
 console.log('Opening page');await page.goto('http://127.0.0.1:8067/admin/reports/dhl');await page.getByLabel('Reporting month',{exact:true}).fill('2026-09');
 console.log('Uploading raw');await page.getByLabel('DHL Trips Summary',{exact:true}).setInputFiles(f.raw_path);await page.getByText('File saved. Calculations updated.',{exact:true}).waitFor();
 console.log('Uploading expenses');const saved=page.waitForResponse(r=>r.url().endsWith('/expenses')&&r.request().method()==='POST');await page.getByLabel('Net Summary Expenses',{exact:true}).setInputFiles(f.net_path);assert.equal((await saved).status(),200);
 await page.getByRole('button',{name:'Review KAY025L',exact:true}).waitFor();await page.reload();await page.getByLabel('Reporting month',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'Review KAY025L',exact:true}).waitFor();
 console.log('Reopened files');const before=await state(),row=before.report.rows.find(r=>r.normalized_plate==='KAY025L');assert.equal(row.gross,'201891.81');assert.equal(row.net_payable,'101630.52');assert.equal(before.files.raw_files.length,1);assert.equal(before.files.expense_files.length,1);
 console.log('Confirming isolated truck');await page.getByRole('button',{name:'Review KAY025L',exact:true}).click();const dialog=page.getByRole('dialog',{name:'Review KAY025L',exact:true});if(await dialog.getByRole('checkbox').count())await dialog.getByRole('checkbox').check();const download=page.waitForEvent('download');await dialog.getByRole('button',{name:/^(Confirm and issue payslip|Download payslip)$/}).click();const dl=await download,pdf=fs.readFileSync(await dl.path());fs.writeFileSync('/private/tmp/smithsons-reliability-real-kay.pdf',pdf,{mode:0o600});assert.ok(pdf.length>1000);
 if(await page.getByRole('dialog').count())await page.getByRole('button',{name:'Close',exact:true}).click();const after=await state();assert.equal(after.report.status,'draft');assert.equal(after.report.rows.find(r=>r.normalized_plate==='KBC554F').truck_confirmation.record,null);
 await page.getByLabel('Net Summary Expenses',{exact:true}).setInputFiles(f.corrected_path);await page.getByText('File saved. Calculations updated.',{exact:true}).waitFor();const revised=await state();assert.equal(revised.files.expense_files.length,2);assert.equal(revised.report.rows.find(r=>r.normalized_plate==='KAY025L').net_payable,'101629.59');
 await page.getByRole('button',{name:'Review KAY025L',exact:true}).click();const next=page.waitForEvent('download');await page.getByRole('button',{name:'Download previous statement',exact:true}).click();assert.deepEqual(fs.readFileSync(await(await next).path()),pdf);assert.deepEqual(errors,[]);
 console.log('PASS: real browser/API/PostgreSQL: two uploads, saved reopen, source reconciliation, independent confirmation, PDF, corrected version and immutable historical PDF.');
}finally{await browser.close();}
