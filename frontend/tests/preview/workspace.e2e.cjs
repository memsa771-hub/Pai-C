/* Run against the fixture Vite server only. No real API or identity is used. */
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {chromium}=require(process.argv[2]||'playwright');
const screenshots=path.resolve(__dirname,'../../../docs/counselor/screenshots');
const base='http://127.0.0.1:4173/student';
(async()=>{
  fs.mkdirSync(screenshots,{recursive:true});
  const browser=await chromium.launch({channel:'msedge'});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
  const page=await context.newPage();const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const shots=[['onboarding','onboarding=1'],['chat','view=threads'],['mirror','view=threads&mirror=1'],
    ['first-picture','view=threads&card=picture'],['rating','view=threads&card=rating'],['fact-card','view=threads&card=fact'],['journey','view=journey'],['paths','view=paths'],['path','view=paths&path=path-one'],
    ['programs','view=paths&path=path-one&stage=H'],['compare','view=compare&roadmap=1'],
    ['plan','view=plan&roadmap=1'],['profile','view=profile'],['documents','view=files'],['settings','view=settings']];
  for(const theme of ['light','dark'])for(const [name,query] of shots){
    await page.goto(`${base}?${query}&theme=${theme}`);
    await page.locator('button').first().waitFor({timeout:10000}).catch(error=>{throw new Error(name+': '+errors.join('; ')+' '+error.message)});
    await page.waitForTimeout(350);
    assert.equal(errors.length,0,`${name}: ${errors.join('; ')}`);
    assert((await page.locator('body').innerText()).length>150,`${name} must render content`);
    await page.screenshot({path:path.join(screenshots,`${name}-${theme}.png`)});
  }
  // A: four entry cards. No hidden extra fields or provider call.
  await page.goto(`${base}?onboarding=1`);
  assert.equal(await page.locator('input').count(),2);
  await page.getByRole('button',{name:'Other',exact:true}).click();
  assert.equal(await page.locator('input').count(),3);
  await page.locator('input').nth(0).fill('Sam Taylor');
  await page.locator('input').nth(1).fill('Secondary education');
  await page.locator('input').nth(2).fill('My city');
  await page.getByRole('button',{name:'English',exact:true}).click();
  const submit=page.getByRole('button',{name:'Continue',exact:true});
  await submit.click();
  await page.waitForURL('**view=threads');
  // B-D: conversation and the calm journey, with every A-K stage present.
  await page.getByRole('button',{name:'Your journey',exact:true}).click();
  await page.getByRole('heading',{name:'Your journey, at your pace'}).waitFor();
  assert.equal(await page.locator('main ol > li').count(),11);
  // E: the actual Mirror control requires agreement then accepts ratings.
  await page.goto(`${base}?view=threads&mirror=1`);
  await page.getByRole('button',{name:'Yes, that is right',exact:true}).click();
  const ratings=page.locator('input[type="number"]');
  await ratings.nth(0).fill('5');await ratings.nth(1).fill('7');
  await page.getByRole('button',{name:'Send',exact:true}).click();
  assert((await page.evaluate(()=>window.__offlineCalls)).some(call=>call.method==='submitCounselorMirrorFeedback'));
  // F-G: paths first. Merely viewing a path must not search programs.
  await page.getByRole('button',{name:'Paths',exact:true}).click();
  await page.getByRole('button',{name:'Explore',exact:true}).first().click();
  await page.getByRole('heading',{name:'What it is',exact:true}).waitFor();
  assert(!(await page.evaluate(()=>window.__offlineCalls)).some(call=>call.method==='searchPrograms'));
  // H: the student explicitly opens places and confirms the search.
  await page.getByRole('button',{name:'Where could I study this?',exact:true}).click();
  const search=page.getByRole('button',{name:'Look at programs',exact:true});
  assert(await search.isDisabled());
  await page.getByRole('checkbox').check();await search.click();
  await page.getByText('No verified program information is available yet.',{exact:false}).waitFor();
  // I-J: reviewed roadmap handoff; no automatic choice is fabricated.
  await page.getByRole('button',{name:'Prepare a reviewed roadmap'}).click();
  await page.getByRole('heading',{name:'Compare paths',exact:true}).waitFor();
  assert(!(await page.evaluate(()=>window.__offlineCalls)).some(call=>call.method==='chooseRoadmap'));
  const choose=page.getByRole('button',{name:'Choose route',exact:true});
  await choose.click();
  const dialog=page.getByRole('dialog');
  await dialog.getByRole('button',{name:'Choose route',exact:true}).click();
  await dialog.getByRole('status').waitFor();
  const choiceCalls=(await page.evaluate(()=>window.__offlineCalls));
  assert.equal(choiceCalls.filter(call=>call.method==='getRoadmapChoiceToken').length,1);
  assert.equal(choiceCalls.filter(call=>call.method==='chooseRoadmap').length,1);
  for(const theme of ['light','dark']){
    await page.goto(`${base}?view=compare&roadmap=1&theme=${theme}`);
    await page.getByRole('button',{name:'Choose route',exact:true}).click();
    await page.getByRole('dialog').getByRole('button',{name:'Choose route',exact:true}).click();
    await page.getByRole('dialog').getByRole('status').waitFor();
    await page.waitForTimeout(300);
    await page.screenshot({path:path.join(screenshots,`decision-${theme}.png`)});
    await page.getByRole('dialog').getByRole('button',{name:'Close',exact:true}).first().click();
  }
  await page.getByRole('button',{name:'Plan & check-ins',exact:true}).click();
  await page.getByRole('heading',{name:'Small next steps'}).waitFor();
  // K: return to the same conversation with a check-in draft, not an auto-send.
  await page.getByRole('button',{name:'Open conversation',exact:true}).click();
  assert(!(await page.evaluate(()=>window.__offlineCalls)).some(call=>call.method==='sendMessage'));
  // Privacy and theme controls render on a phone without horizontal overflow.
  await page.setViewportSize({width:390,height:844});
  await page.goto(`${base}?view=profile&theme=dark`);await page.getByRole('heading',{name:'A living picture of you'}).waitFor();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(screenshots,'profile-mobile-dark.png')});
  assert.equal(errors.length,0,errors.join('; '));
  console.log('PASS: 32 light/dark screens, mobile overflow, A-K UI flow including explicit choice and consent boundaries. Synthetic backend; no live calls.');
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
