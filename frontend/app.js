// Production API base: same-origin by default (no localhost dependency).
// For Capacitor/native builds, set window.BACKEND_URL or <meta name="backend-url"> to the production HTTPS API.
const BACKEND_URL = (window.BACKEND_URL || document.querySelector('meta[name="backend-url"]')?.content || '').replace(/\/$/, '');
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
let state={classes:[],currentUser:null, role:null};

// ---- FRONTEND RBAC MATRIX (mirrors backend) ----
const VIEW_ROLES = {
  dashboard: ['admin','teacher','student','parent'],
  students: ['admin','teacher'],
  attendance: ['admin','teacher','student','parent'],
  classes: ['admin','teacher','student','parent'],
  staff: ['admin'],
  parents: ['admin'],
  messages: ['admin','teacher'],
  holidays: ['admin','teacher','student','parent'],
  datesheet: ['admin','teacher','student','parent'],
  reports: ['admin','teacher','student','parent'],
  settings: ['admin'],
  qr: ['admin','teacher'],
  monthly: ['admin','teacher','student','parent'],
  notices: ['admin','teacher','student','parent'],
  enotes: ['admin','teacher','student','parent'],
  meals: ['admin'],
  scholarship: ['admin'],
  complaints: ['admin','teacher','student','parent'],
  calendar: ['admin','teacher','student','parent'],
  analytics: ['admin','teacher'],
  notifications: ['admin','teacher','student','parent'],
  teachers: ['admin'],
  timetable: ['admin','teacher','student','parent'],
  heatmap: ['admin','teacher'],
  studentid: ['admin','teacher','student','parent'],
  reviews: ['admin','teacher','student','parent'],
  features: ['admin','teacher','student','parent'],
  attcal: ['admin','teacher','student','parent'],
  homework: ['admin','teacher','student','parent'],
  exams: ['admin','teacher','student','parent'],
  profile: ['admin','teacher','student','parent'],
  password: ['admin','teacher','student','parent'],
  editprofile: ['admin','teacher','student','parent'],
  accountsettings: ['admin','teacher','student','parent'],
  privacy: ['admin','teacher','student','parent'],
  onboarding: ['admin','teacher','student','parent'],
  'denied': ['admin','teacher','student','parent']
};
function canView(role, view){
  const allowed = VIEW_ROLES[view] || [];
  return allowed.includes(role);
}
function filterNavByRole(role){
  $$('#nav button, .nav-mini button').forEach(b=>{
    const v=b.dataset.view;
    if(!v) return;
    const ok = canView(role, v);
    b.style.display = ok ? '' : 'none';
  });
  // also hide quick access label if all hidden?
}
function showDenied(role, view){
  $$('.view').forEach(s=>s.classList.remove('active'));
  const d=$('#view-denied');
  if(d) d.classList.add('active');
  const r=$('#deniedRole');
  if(r) r.textContent = role + ' → ' + view;
}

function toast(msg, ok=true){
  const t=document.createElement('div');
  t.className='toast '+(ok?'ok':'err');
  t.setAttribute('role','status');
  t.innerHTML=icon(ok?'circle-check':'circle-alert')+'<span></span>';
  t.querySelector('span').textContent=msg;
  const c=$('#toast'); if(c) c.appendChild(t);
  setTimeout(()=>{ t.style.opacity='0'; t.style.transform='translateY(8px)'; setTimeout(()=>t.remove(),250); },3200);
}
function togglePwd(){ const i=$('#loginPass'); i.type=i.type==='password'?'text':'password'; }
async function api(p,opts={}){
  opts.credentials = opts.credentials || 'same-origin';
  if(!opts.headers) opts.headers={};
  // ensure cookie sent
  const r=await fetch(p.startsWith('/') ? BACKEND_URL + p : p, opts);
  const j=await r.json().catch(()=>({}));
  /* Attach status + parsed body to the thrown Error so callers can react to
     structured failures (the timetable conflict list, say) without a second
     request. Existing callers only read .message, so this is additive. */
  const fail=(msg)=>{ const e=new Error(msg||'Error'); e.status=r.status; e.body=j; return e; };
  if(r.status===401){
    // not authenticated -> show login
    $('#appShell')?.classList.add('hidden');
    const ls=$('#loginScreen');
    if(ls) ls.style.display='flex';
    throw fail(j.error||'Not authenticated');
  }
  if(r.status===403){
    // Surface the reason without hijacking the view the user is looking at.
    // (view-level denial is handled by navigate() -> showDenied())
    toast(j.error||'Access denied', false);
    throw fail(j.error||'Access denied');
  }
  if(!r.ok) throw fail(j.error||'Error');
  return j;
}
/* Staff-only editing controls stay out of the way for students/parents.
   Presentation only — the backend rejects those writes regardless of the UI. */
function syncStaffOnlyControls(){
  const staff = ['admin','teacher'].includes(state.role);
  ['#classToolbar','#dsToolbar','#noticeToolbar','#enoteToolbar'].forEach(sel=>{
    const el = document.querySelector(sel);
    if(el) el.classList.toggle('hidden', !staff);
  });
}
function navigate(v){
  const role = state.role || 'admin';
  // Students/parents never mark the roster — send them to their own calendar.
  if((role==='student' || role==='parent') && v==='attendance') v='attcal';
  if(!canView(role, v)){
    showDenied(role, v);
    toast('Access denied for '+role,false);
    return;
  }
  $$('#nav button, .nav-mini button').forEach(b=>b.classList.toggle('active', b.dataset.view===v));
  $$('.view').forEach(s=>s.classList.toggle('active', s.id==='view-'+v));
  syncMobileNav(v);
  closeMoreSheet();
  syncStaffOnlyControls();
  if(v==='features') v='features';
  const t=document.querySelector(`[data-view="${v}"]`)?.textContent?.trim() || VIEW_LABELS[v] || v;
  const pt=$('#pageTitle'); if(pt) pt.textContent=t;
  if(innerWidth<900) closeSidebar();
  if(v==='dashboard') loadDashboard();
  if(v==='students') loadStudents();
  if(v==='attendance') initAttendance();
  if(v==='monthly') initMonthly();
  if(v==='classes') loadClasses();
  if(v==='staff') loadStaff();
  if(v==='parents') loadParents();
  if(v==='teachers') loadTeachers();
  if(v==='calendar') initCalendar();
  if(v==='analytics') loadAnalytics();
  if(v==='notifications') loadNotifPage();
  if(v==='timetable') loadTimetable();
  if(v==='heatmap') initHeatmap();
  if(v==='studentid') initIdCard();
  if(v==='reviews') loadReviews();
  if(v==='messages') loadWhatsApp();
  if(v==='holidays') loadHolidays();
  if(v==='datesheet') loadDateSheets();
  if(v==='reports') {initReports(); loadMarksReport(); initMarksChips();}
  if(v==='qr') {}
  if(v==='notices') loadNotices();
  if(v==='enotes') loadENotes();
  if(v==='attcal') loadAttCal();
  if(v==='homework') loadHomeworkView();
  if(v==='exams') loadExamReport();
  if(v==='profile') loadProfileView();
  if(v==='password') loadPasswordView();
  if(v==='editprofile') epLoad();
  if(v==='accountsettings') asLoad();
  if(v==='privacy') pvLoad();
  if(v==='onboarding') obLoad();
  if(v==='meals') loadMeals();
  if(v==='scholarship') loadScholarships();
  if(v==='complaints') loadComplaints();
  if(v==='settings') loadSettings();
  syncMobileNav(v);
  setTimeout(paintIcons,50);
}
$$('#nav button, .nav-mini button').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.view)));
const mb=$('#menuBtn'); if(mb) mb.onclick=()=>$('#sidebar').classList.toggle('open');
function toggleProfile(){ $('#profileDrop')?.classList.toggle('hidden'); }
async function logout(){
  try{ await fetch(BACKEND_URL + '/api/auth/logout',{method:'POST',credentials:'same-origin'}); }catch(e){}
  state.currentUser=null; state.role=null;
  if(typeof logoutPortal==='function') logoutPortal();
  $('#appShell')?.classList.add('hidden');
  const ls=$('#loginScreen'); if(ls) ls.style.display='flex';
  if(typeof showLoginCard==='function') showLoginCard((typeof portal!=='undefined' && portal.mode) ? portal.mode : 'staff');
  toast('Logged out');
}
function globalSearch(){ const q=$('#globalSearch')?.value.toLowerCase()||''; if(q.length<2) return; if(['student','class','attendance'].some(w=>q.includes(w))) navigate(q.includes('student')?'students':q.includes('attendance')?'attendance':'classes'); }
async function loadLoginSchoolInfo(){
  try{
    const s=await fetch(BACKEND_URL + '/api/settings',{credentials:'same-origin'}).then(r=>r.json());
    const name=s.school_name||'Dynamic Attendance App';
    const logo=s.logo_path;
    // left panel keeps the Dynamic CuroBase brand; the school name goes in the sub-line
    const leftH1=document.querySelector('.login-left h1');
    if(leftH1) leftH1.textContent='Dynamic CuroBase';
    const leftSub=document.querySelector('.login-left .sub');
    if(leftSub) leftSub.textContent=name;
    const loginLogo=$('#loginLogo'), loginName=$('#loginSchoolName');
    if(loginName) loginName.textContent=name;
    ['#studentLoginSchoolName','#parentLoginSchoolName'].forEach(sel=>{
      const e2=document.querySelector(sel); if(e2) e2.textContent=name;
    });
    const brandIcon=document.getElementById('loginBrandIcon');
    if(loginLogo && logo){
      loginLogo.src=`${BACKEND_URL}/api/logo/${logo}`;
      loginLogo.classList.remove('hidden');
      if(brandIcon) brandIcon.innerHTML=`<img src="${BACKEND_URL}/api/logo/${logo}" alt="">`;
    }
  }catch(e){}
}
async function doLogin(e){
  if(e) e.preventDefault();
  if(typeof logoutPortal==='function') logoutPortal();
  if(typeof portal!=='undefined') portal.mode='staff';
  const u=$('#loginUser').value.trim(), p=$('#loginPass').value;
  const msgEl=$('#loginMsg'), btn=$('#loginBtn');
  if(!u || !p){ if(msgEl) msgEl.textContent='Username and password required'; toast('Username and password required',false); return; }
  if(btn){ btn.disabled=true; btn.classList.add('btn-loading'); btn.innerHTML='<span class="spinner"></span> Signing in…'; }
  if(msgEl) msgEl.textContent='';
  try{
    // Remember Me
    const remember=$('#rememberMe')?.checked;
    if(remember) localStorage.setItem('rememberUser', u); else localStorage.removeItem('rememberUser');
    const r=await fetch(BACKEND_URL + '/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({username:u,password:p})});
    const j=await r.json();
    if(!r.ok) throw new Error(j.error||'Login failed');
    state.currentUser=j.user; state.role=j.user.role;
    $('#loginScreen').style.display='none'; $('#appShell').classList.remove('hidden');
    const role=j.user.role;
    const topName=$('#topName'), topRole=$('#topRole');
    if(topName) topName.textContent=j.user.username;
    if(topRole) topRole.textContent=role;
    const pdN=$('#pdName'), pdR=$('#pdRole');
    if(pdN) pdN.textContent=j.user.username;
    if(pdR) pdR.textContent=role+' • '+(document.querySelector('.school-name')?.textContent?.split('🇮')[0]?.trim()||'School');
    const dt=$('#dashTeacher'); if(dt) dt.textContent=j.user.username;
    const bd=$('#bellDot'); if(bd) bd.style.display='none';
    filterNavByRole(role);
    buildMobileNav();
    toast('Welcome '+j.user.username+' ('+role+')');
    // role-based redirect: all go to dashboard which adapts per role
    navigate('dashboard');
    loadDashboard(); loadClasses(); loadSettings();
  }catch(e){ if(msgEl) msgEl.textContent=e.message; toast(e.message,false); }
  finally{ if(btn){ btn.disabled=false; btn.classList.remove('btn-loading'); btn.innerHTML='Login '+icon('arrow-right'); } }
}
// init time badge
setInterval(()=>{ const b=$('#todayBadge'); if(b) b.textContent=new Date().toLocaleDateString('en-IN',{weekday:'short',day:'2-digit',month:'short',year:'numeric'}); },1000);

// helpers for class/section selects
async function loadClasses(){
  try{
  const data=await api('/api/classes'); state.classes=data;
  const opts=data.map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
  const allOpts='<option value="">All / Select</option>'+opts;
  ['#s_class','#attClass','#monClass','#repClass','#secClass','#waClass','#dsClass','#mealClass','#f_class','#calClass','#anaClass','#ttClass','#qrTmpClass','#repAClass'].forEach(sel=>{ const el=$(sel); if(el) el.innerHTML=allOpts; });
  try{
    const subs=await api('/api/subjects');
    const sopts='<option value="">No subject</option>'+subs.map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
    const qts=$('#qrTmpSubject'); if(qts) qts.innerHTML=sopts;
  }catch(e){}
  const grid=$('#classGrid');
  if(grid){
    const counts=await Promise.all(data.map(async c=>{
      let s=[]; try{ s=await api('/api/students?class_id='+c.id); }catch(e){ s=[]; }
      return {c, count:Array.isArray(s)?s.length:0};
    }));
    // hide Add/Remove for non-admin
    const canManage = state.role==='admin';
    grid.innerHTML=counts.map(({c,count})=>`
      <div class="class-card">
        <h4>Class ${c.name} ${c.name==='10'||c.name==='12'?'🎓':''}</h4>
        <p class="muted">${count} students • ${c.sections.length} sections</p>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0">${c.sections.map(s=>`<span class="pill">${s.name} ${canManage?`<a href="#" onclick="delSection(${s.id});return false" style="color:var(--red)">✕</a>`:''}</span>`).join('')}</div>
        <div class="bar-track"><div class="bar-fill g" style="width:${Math.min(90, 60+count*2)}%"></div></div>
        <small class="muted">${Math.min(98, 88+count)}% attendance</small>
        ${canManage?`<div style="margin-top:8px;display:flex;gap:6px"><button class="btn-outline" onclick="delClass(${c.id})">Remove</button></div>`:''}
      </div>`).join('');
  }
  const secList=$('#sectionList');
  if(secList) secList.innerHTML='<h3>Sections Detail</h3>'+data.map(c=>`<div style="padding:8px;border-bottom:1px solid #f1f5f9"><b>Class ${c.name}:</b> ${c.sections.map(s=>`${s.name}`).join(', ')}</div>`).join('');
  filterSections();
  }catch(e){ if(e.message.includes('Access denied')) showDenied(state.role||'guest','classes'); }
}
function filterSection(sel){
  const map={'#s_section':'#s_class','#attSection':'#attClass','#monSection':'#monClass','#waSection':'#waClass','#f_section':'#f_class','#calSection':'#calClass','#anaSection':'#anaClass','#repASection':'#repAClass','#ttSection':'#ttClass'};
  const classSel=map[sel]; if(!classSel) return;
  const cid=$(classSel)?.value; const el=$(sel); if(!el) return;
  if(!cid){ el.innerHTML='<option value="">All / Select</option>'; return; }
  const cls=state.classes.find(x=>x.id==cid);
  el.innerHTML='<option value="">All / Select</option>'+(cls?.sections||[]).map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
}
function filterSections(){ ['#s_section','#attSection','#monSection','#waSection','#f_section','#calSection','#anaClass','#anaSection','#repASection','#ttSection'].forEach(s=>filterSection(s)); }
async function addClass(){ if(state.role!=='admin') return toast('Admin only',false); const n=$('#newClass').value.trim(); if(!n) return; try{await api('/api/classes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})}); $('#newClass').value=''; loadClasses(); toast('Class added');}catch(e){toast(e.message,false)} }
async function delClass(id){ if(state.role!=='admin') return toast('Admin only',false); if(!confirm('Delete class?')) return; try{await api('/api/classes?id='+id,{method:'DELETE'}); loadClasses(); toast('Deleted');}catch(e){toast(e.message,false)} }
async function addSection(){ if(state.role!=='admin') return toast('Admin only',false); const cid=$('#secClass').value, name=$('#newSec').value.trim(); if(!cid||!name) return toast('Select class & section (A-K)',false); try{await api('/api/sections',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class_id:cid,name})}); loadClasses(); toast('Section '+name+' added');}catch(e){toast(e.message,false)} }
async function addSectionsAK(){
  if(state.role!=='admin') return toast('Admin only',false);
  const cid=$('#secClass').value;
  if(!cid) return toast('Select class first',false);
  const letters=['A','B','C','D','E','F','G','H','I','J','K'];
  let added=0, skipped=0;
  for(const L of letters){
    try{ await api('/api/sections',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class_id:cid,name:L})}); added++; }catch(e){ skipped++; }
  }
  await loadClasses();
  toast(`Sections A-K: ${added} added, ${skipped} already existed`);
}
async function delSection(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/sections?id='+id,{method:'DELETE'}); loadClasses(); toast('Section removed');}catch(e){toast(e.message,false)} }

// DASHBOARD (gov-portal style, 6 cards + charts)
async function loadDashboard(){
  try{
  const s=await api('/api/dashboard/summary').catch(()=>({total_students:0,total_classes:0}));
  const el=(id,v)=>{ const e=document.getElementById(id); if(e) e.textContent=v; };
  const sessName=s.session||'2026–27';
  const ds=$('#dashSession'); if(ds) ds.textContent=sessName;
  const ts=$('#topSession'); if(ts) ts.textContent=sessName;
  const tsn=$('#topSchoolName'); if(tsn) tsn.textContent=s.school_name||'Smart Attendance';
  const rb=$('#roleBadge'); if(rb) rb.textContent=(state.role||'').toUpperCase();
  if(state.role==='student' || state.role==='parent'){
    // dedicated Student / Parent portal home (rendered by portal.js)
    const si=document.getElementById('schoolInfo');
    if(si) si.innerHTML='<b>'+(state.role==='parent'?'Parent':'Student')+' Dashboard</b> • Session '+sessName;
    if(typeof loadPortalHome==='function') loadPortalHome();
    loadNotifBadge();
    return;
  }
  // staff session: make sure a portal home from an earlier student/parent
  // login is not left on screen
  const portalHome=document.getElementById('portalHome');
  if(portalHome) portalHome.classList.add('hidden');
  const dashEl=document.getElementById('view-dashboard');
  if(dashEl) dashEl.classList.remove('portal-mode');
  el('kpiTotal', s.total_students??'-');
  el('kpiPresent', s.present_today??'-');
  el('kpiAbsent', s.absent_today??'-');
  el('kpiLate', s.late_today??'-');
  el('kpiLeave', s.leave_today??'-');
  el('kpiRate', (s.attendance_rate??'-')+'%');
  el('kpiClasses', s.total_classes??'-');
  const kt=$('#kpiTeachers'); if(kt) kt.textContent=s.total_teachers??'-';
  const dashDate=document.getElementById('dashDate');
  if(dashDate && !dashDate.value) dashDate.value=new Date().toISOString().slice(0,10);
  const date=dashDate?.value || new Date().toISOString().slice(0,10);
  const d=await api('/api/attendance/dashboard?date='+date).catch(()=>({present:0,absent:0,leave:0,late:0,not_marked:0,percentage:0}));
  el('legP', d.present); el('legA', d.absent); el('legL', d.leave);
  const lt=$('#legT'); if(lt) lt.textContent=d.late||0;
  el('legN', d.not_marked||0);
  const donut=document.getElementById('donut'); if(donut){ donut.style.setProperty('--p', d.percentage||0); const sp=donut.querySelector('span'); if(sp) sp.textContent=(d.percentage||0)+'%'; }
  const si=document.getElementById('schoolInfo'); if(si) si.innerHTML=`<b>${s.total_classes||0} Classes</b> • ${s.total_teachers||0} Teachers • ${s.total_parents||0} Parents • Session ${sessName}<br><span class="pill g">Online • SQLite DB</span>`;
  // weekly chart
  try{
    const ana=await api('/api/analytics');
    const wc=$('#weeklyChart');
    if(wc) wc.innerHTML=ana.weekly.map(w=>`<div style="height:${Math.max(4,w.percentage)}%" title="${w.date} ${w.percentage}%"><span>${w.percentage}%</span></div>`).join('');
  }catch(e){}
  const tc=document.getElementById('todayClasses');
  if(tc){ try{
    const ana2=await api('/api/analytics');
    tc.innerHTML=ana2.class_comparison.slice(0,5).map(c=>`<div class="bar-row"><span class="bar-label">Class ${c.class}</span><div class="bar-track"><div class="bar-fill g" style="width:${Math.min(100, c.total? (c.present_records/Math.max(1,c.total*7)*100):0)}%"></div></div><span class="pct">${c.total} stud</span></div>`).join('');
  }catch(e){} }
  loadNotifBadge();
  loadCommandCenter();
  loadRecentActivity();
  const dsl=$('#dashSchoolLine'); if(dsl) dsl.textContent=s.school_name||'Smart School Attendance Management System';
  }catch(e){ console.error('dashboard',e); if(!String(e.message||'').includes('Access denied')) toast('Dashboard load failed',false); }
}

// STUDENTS
function openStudentModal(edit=null){
  if(state.role && !['admin','teacher'].includes(state.role)) return toast('Access denied: cannot add students',false);
  $('#studentModal').classList.add('open');
  if(edit){
    if(state.role==='teacher' && edit.id) { /* teacher can edit but limited */ }
    $('#studentModalTitle').textContent='Edit Student';
    $('#f_student_id').value=edit.student_id; $('#f_student_id').disabled=true;
    $('#f_roll').value=edit.roll_no||''; $('#f_name').value=edit.name;
    $('#f_class').value=edit.class_id||''; filterSection('#f_section'); $('#f_section').value=edit.section_id||'';
    $('#f_father').value=edit.father_name||''; $('#f_mother').value=edit.mother_name||''; $('#f_phone').value=edit.phone||''; $('#f_address').value=edit.address||''; $('#f_dob').value=edit.dob||'';
    const gg=$('#f_gender'); if(gg) gg.value=edit.gender||'';
    const ad=$('#f_admission'); if(ad) ad.value=edit.admission_no||'';
    const em=$('#f_email'); if(em) em.value=edit.email||'';
    const pn=$('#f_parentname'); if(pn) pn.value=edit.parent_name||edit.father_name||'';
    const pc=$('#f_parentcontact'); if(pc) pc.value=edit.parent_contact||edit.phone||'';
    $('#studentModal').dataset.editId=edit.id;
    $('#qrPreview').innerHTML=`<img src="${BACKEND_URL}/api/students/${edit.student_id}/qr" style="width:80px;height:80px;border:1px solid #e2e8f0;border-radius:8px">`;
  } else {
    $('#studentModalTitle').textContent='Add Student';
    $('#f_student_id').disabled=false; $('#studentModal').dataset.editId='';
    ['#f_student_id','#f_roll','#f_name','#f_father','#f_mother','#f_phone','#f_address','#f_dob','#f_admission','#f_email','#f_parentname','#f_parentcontact'].forEach(s=>{const el=$(s); if(el) el.value='';}); const gg2=$('#f_gender'); if(gg2) gg2.value='';
    $('#qrPreview').innerHTML='<span class="muted sm">QR auto-generated</span>';
    const pf=$('#f_photo'); if(pf) pf.value='';
  }
}
function closeStudentModal(){ $('#studentModal').classList.remove('open'); }
async function saveStudent(){
  const editId=$('#studentModal').dataset.editId;
  const payload={student_id:$('#f_student_id').value.trim(), roll_no:$('#f_roll').value.trim(), name:$('#f_name').value.trim(), class_id:$('#f_class').value||null, section_id:$('#f_section').value||null, father_name:$('#f_father').value, mother_name:$('#f_mother').value, phone:$('#f_phone').value, address:$('#f_address').value, dob:$('#f_dob').value, gender:$('#f_gender')?.value||'', admission_no:$('#f_admission')?.value||'', email:$('#f_email')?.value||'', parent_name:$('#f_parentname')?.value||'', parent_contact:$('#f_parentcontact')?.value||''};
  if(payload.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(payload.email)){ $('#studentModalMsg').textContent='Invalid email'; return; }
  if(!payload.student_id||!payload.name) {$('#studentModalMsg').textContent='Student ID & Name required'; return;}
  const file=$('#f_photo')?.files[0];
  try{
    if(file){
      const fd=new FormData(); Object.entries(payload).forEach(([k,v])=>fd.append(k,v||'')); fd.append('photo',file);
      if(editId) fd.append('id', editId);
      const r=await fetch(BACKEND_URL + '/api/students',{method: editId ? 'PUT' : 'POST', body:fd, credentials:'same-origin'}); const j=await r.json(); if(!r.ok) throw new Error(j.error);
    } else {
      if(editId) await api('/api/students',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:editId,...payload})});
      else await api('/api/students',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    }
    closeStudentModal(); loadStudents(); toast('Student saved ✅');
  }catch(e){$('#studentModalMsg').textContent=e.message; toast(e.message,false)}
}
async function loadStudents(){
  const q=$('#s_q')?.value||'', cid=$('#s_class')?.value||'', sid=$('#s_section')?.value||'';
  const params=new URLSearchParams(); if(q) params.set('q',q); if(cid) params.set('class_id',cid); if(sid) params.set('section_id',sid);
  let data=[];
  try{ data=await api('/api/students?'+params.toString()); }catch(e){ if(e.message.includes('Access denied')){ $('#studentsTable').innerHTML=`<div style="padding:24px;text-align:center" class="muted">🔒 Access denied for ${state.role}</div>`; return;} data=[]; }
  const demo=[
    {photo:'', student_id:'STU001', roll_no:'01', name:'Aarav Sharma', class_name:'10', section_name:'A', father_name:'R. Sharma', phone:'9876543210', id:1},
    {photo:'', student_id:'STU002', roll_no:'02', name:'Priya Verma', class_name:'10', section_name:'A', father_name:'S. Verma', phone:'9876543211', id:2},
    {photo:'', student_id:'STU003', roll_no:'03', name:'Rohan Singh', class_name:'10', section_name:'B', father_name:'A. Singh', phone:'9876543212', id:3},
  ];
  const rows=data.length? data : (q||cid||sid? [] : (state.role==='student'||state.role==='parent'? [] : demo));
  const canEdit = ['admin','teacher'].includes(state.role);
  const canDelete = state.role==='admin';
  const html= rows.length? `<table><thead><tr><th>Photo</th><th>Student Name</th><th>Student ID</th><th>Roll No.</th><th>Class</th><th>Section</th><th>Status</th><th>Actions</th></tr></thead><tbody>`+rows.map(s=>{
    const avatar=s.photo? `${BACKEND_URL}/api/photos/${s.photo}` : `https://ui-avatars.com/api/?name=${encodeURIComponent(s.name)}&background=2563eb&color=fff&size=64`;
    return `<tr>
      <td><img src="${avatar}" class="avatar"></td>
      <td><b>${s.name}</b><br><small class="muted">${s.father_name||''}</small></td>
      <td><span class="pill" style="background:#eef2ff;color:#3730a3">${s.student_id}</span></td>
      <td>${s.roll_no||''}</td>
      <td>${s.class_name||''}</td>
      <td><span class="pill" style="background:#f1f5f9">${s.section_name||''}</span></td>
      <td><span class="badge P">Active</span></td>
      <td>${canEdit?`<button class="btn-outline" onclick='openStudentModal(${JSON.stringify(s).replace(/'/g,"&#39;")})'>Edit</button>`:''} ${canDelete?`<button class="btn-red" style="padding:6px 10px" onclick="delStudent(${s.id})">Delete</button>`:''} <button class="btn-outline" onclick="showQRFor(&quot;${s.student_id}&quot;)">QR</button></td>
    </tr>`;
  }).join('')+`</tbody></table>` : `<div style="padding:24px;text-align:center" class="muted">No students found. ${canEdit?'Click “+ Add Student”.':''}</div>`;
  const el=$('#studentsTable'); if(el) el.innerHTML=html;
  const schSel=$('#schStudent'); if(schSel) schSel.innerHTML=rows.map(s=>`<option value="${s.id}">${s.name} (${s.student_id})</option>`).join('');
}
async function delStudent(id){ if(state.role!=='admin') return toast('Admin only: cannot delete',false); if(!confirm('Delete student?')) return; try{await api('/api/students?id='+id,{method:'DELETE'}); loadStudents(); toast('Deleted');}catch(e){toast(e.message,false)} }

// ATTENDANCE (session/subject/time + Late + search + offline)
async function loadAttMeta(){
  try{
    const sess=await api('/api/sessions');
    const sel=$('#attSession');
    if(sel){
      const active=sess.find(x=>x.active) || sess[0];
      sel.innerHTML=sess.map(x=>`<option value="${x.name}" ${active&&x.name===active.name?'selected':''}>${x.name}</option>`).join('');
    }
  }catch(e){}
  try{
    const subs=await api('/api/subjects');
    const sel=$('#attSubject');
    if(sel){
      const cur=sel.value;
      sel.innerHTML='<option value="">All Subjects</option>'+subs.map(x=>`<option value="${x.id}">${x.name}</option>`).join('');
      if(cur) sel.value=cur;
    }
  }catch(e){}
}
function initAttendance(){ const t=new Date().toISOString().slice(0,10); const el=$('#attDate'); if(el && !el.value) el.value=t; loadAttMeta().then(loadAttendance); if(!$('#attDate').value) $('#attDate').value=t; }
function updateOfflineBadge(){ const b=$('#offlineBadge'); if(b) b.classList.toggle('hidden', navigator.onLine); }
window.addEventListener('online', ()=>{ updateOfflineBadge(); toast('Back online — syncing'); const q=JSON.parse(localStorage.getItem('attQueue')||'[]'); if(q.length){ flushAttQueue(); } });
window.addEventListener('offline', updateOfflineBadge);
async function flushAttQueue(){
  const q=JSON.parse(localStorage.getItem('attQueue')||'[]');
  if(!q.length) return;
  for(const item of q){
    try{ await api('/api/attendance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(item)}); }catch(e){}
  }
  localStorage.setItem('attQueue','[]');
  toast('Offline queue synced ✅');
  loadAttendance();
}
async function loadAttendance(){
  updateOfflineBadge();
  const date=$('#attDate').value, cid=$('#attClass').value, sid=$('#attSection').value;
  const subj=$('#attSubject')?.value||'';
  const q=($('#attSearch')?.value||'').toLowerCase();
  let data; try{ data=await api(`/api/attendance?date=${date}&class_id=${cid}&section_id=${sid}&subject_id=${subj}`); }catch(e){ if(String(e.message).includes('Access denied')){ $('#attTable').innerHTML=`<div class="muted" style="padding:16px">🔒 ${e.message}</div>`; return;} data={students:[], is_holiday:false}; }
  const dow=new Date(date).toLocaleDateString('en-IN',{weekday:'long', day:'numeric', month:'long', year:'numeric'});
  const wd=$('#attWeekday'); if(wd) wd.textContent=dow;
  const warn=$('#holidayWarn'); if(warn){ if(data.is_holiday){ warn.textContent='🔵 Holiday — '+(data.holiday?.name||'Sunday')+' — Attendance blocked'; warn.classList.remove('hidden'); } else warn.classList.add('hidden'); }
  let dash; try{ dash=await api(`/api/attendance/dashboard?date=${date}&class_id=${cid}&section_id=${sid}&subject_id=${subj}`); }catch(e){ dash={total:0, present:0, absent:0, leave:0, late:0, not_marked:0, percentage:0}; }
  const totalSys=dash.total||0;
  const sumEl=$('#attSummary'); if(sumEl) sumEl.innerHTML=`
    <div class="stat-card green"><div class="stat-icon">${icon('circle-check')}</div><div><small>Present</small><b>${dash.present}</b></div></div>
    <div class="stat-card red"><div class="stat-icon">${icon('circle-x')}</div><div><small>Absent</small><b>${dash.absent}</b></div></div>
    <div class="stat-card yellow"><div class="stat-icon">${icon('clock')}</div><div><small>Late</small><b>${dash.late||0}</b></div></div>
    <div class="stat-card blue"><div class="stat-icon">${icon('user')}</div><div><small>Leave</small><b>${dash.leave}</b></div></div>
    <div class="stat-card blue"><div class="stat-icon">${icon('chart-column')}</div><div><small>Total / %</small><b>${totalSys} • ${dash.percentage}%</b></div></div>`;
  let rows=data.students;
  if(q) rows=rows.filter(s=>(s.name+' '+(s.student_id||'')+' '+(s.roll_no||'')).toLowerCase().includes(q));
  const cnt=$('#attCount'); if(cnt) cnt.textContent=`${rows.length} students`;
  const canMark = ['admin','teacher'].includes(state.role);
  if(!rows.length){
    const hasFilter=cid||sid;
    if(hasFilter){
      $('#attTable').innerHTML=`<div style="padding:24px;text-align:center" class="muted">No students for this class/section. Add students in Students tab.</div>`;
      return;
    }
    if(state.role==='student' || state.role==='parent'){
      $('#attTable').innerHTML=`<div style="padding:24px;text-align:center" class="muted">No attendance records for your profile yet.</div>`;
      return;
    }
    rows=[
      {id:1, roll_no:'01', name:'Aarav Sharma', student_id:'STU001', status:'P', leave_reason:''},
      {id:2, roll_no:'02', name:'Priya Verma', student_id:'STU002', status:'A', leave_reason:''},
      {id:3, roll_no:'03', name:'Rohan Singh', student_id:'STU003', status:'', leave_reason:''},
    ];
  }
  const attTable=$('#attTable');
  if(!attTable) return;
  if(!canMark){
    // view only
    attTable.innerHTML=`<table><thead><tr><th>#</th><th>Student Name</th><th>Status</th><th>Remarks</th></tr></thead><tbody>`+rows.map((s,i)=>`<tr>
      <td>${i+1}</td>
      <td><b>${s.name}</b> <small class="muted">${s.student_id}</small></td>
      <td><span class="badge ${s.status||'P'}">${s.status||'-'}</span></td>
      <td>${s.leave_reason||''}</td>
    </tr>`).join('')+`</tbody></table><div class="muted" style="padding:8px">🔒 View only for ${state.role}</div>`;
    const sa=document.querySelector('.sticky-actions'); if(sa) sa.style.display='none';
    return;
  } else {
    const sa=document.querySelector('.sticky-actions'); if(sa) sa.style.display='flex';
  }
  const bgFor=(st)=>st==='P'?'#dcfce7':st==='A'?'#fee2e2':st==='T'?'#fef3c7':st==='L'?'#dbeafe':'#f1f5f9';
  attTable.innerHTML=`<table><thead><tr><th>Roll No.</th><th>Student</th><th>Status</th><th>Time</th><th>Action</th></tr></thead><tbody>`+rows.map((s,i)=>`<tr>
    <td>${s.roll_no||''}</td>
    <td><div style="display:flex;gap:8px;align-items:center"><img src="https://ui-avatars.com/api/?name=${encodeURIComponent(s.name)}&background=${s.status==='P'?'16a34a':s.status==='A'?'dc2626':s.status==='T'?'f59e0b':'2563eb'}&color=fff&size=32" style="width:28px;height:28px;border-radius:50%"><b>${s.name}</b> <small class="muted">${s.student_id}</small></div></td>
    <td>
      <select data-id="${s.id}" class="attStatus" onchange="this.style.background=({'P':'#dcfce7','A':'#fee2e2','T':'#fef3c7','L':'#dbeafe'}[this.value]||'#f1f5f9')" style="padding:6px 10px;border-radius:999px;border:1px solid #e2e8f0;background:${bgFor(s.status)}" aria-label="Status for ${s.name}">
        <option value="" ${!s.status?'selected':''}>—</option>
        <option value="P" ${s.status==='P'?'selected':''}>🟢 Present</option>
        <option value="A" ${s.status==='A'?'selected':''}>🔴 Absent</option>
        <option value="T" ${s.status==='T'?'selected':''}>🟡 Late</option>
        <option value="L" ${s.status==='L'?'selected':''}>🔵 Leave</option>
      </select>
    </td>
    <td><input data-time="${s.id}" value="${s.time||new Date().toTimeString().slice(0,5)}" type="time" style="padding:6px;border:1px solid #e2e8f0;border-radius:8px" aria-label="Time"></td>
    <td><input data-reason="${s.id}" value="${s.leave_reason||''}" placeholder="Remarks" style="width:100%;padding:6px 10px;border:1px solid #e2e8f0;border-radius:8px" aria-label="Remarks"></td>
  </tr>`).join('')+`</tbody></table>`;
}
function markAll(st){ document.querySelectorAll('.attStatus').forEach(sel=>{ sel.value=st; sel.dispatchEvent(new Event('change')); }); toast('Marked all '+st); }
function resetAttendance(){ document.querySelectorAll('.attStatus').forEach(sel=>{ sel.value=''; }); document.querySelectorAll('[data-reason]').forEach(i=>i.value=''); toast('Reset'); }
function attNav(d){ const dt=new Date($('#attDate').value); dt.setDate(dt.getDate()+d); $('#attDate').value=dt.toISOString().slice(0,10); loadAttendance(); }
function attToday(){ $('#attDate').value=new Date().toISOString().slice(0,10); loadAttendance(); }
function confirmSaveAttendance(){
  if(!['admin','teacher'].includes(state.role)) return toast('Access denied: cannot mark attendance',false);
  const n=document.querySelectorAll('.attStatus').length;
  const marked=[...document.querySelectorAll('.attStatus')].filter(s=>s.value).length;
  const ct=$('#confirmText'); if(ct) ct.textContent=`Save attendance for ${marked}/${n} students on ${$('#attDate').value}? Absent students will trigger parent alerts.`;
  $('#confirmModal').classList.add('open');
}
async function doSaveAttendance(){
  $('#confirmModal').classList.remove('open');
  await saveAttendance();
}
async function saveAttendance(){
  if(!['admin','teacher'].includes(state.role)) return toast('Access denied: cannot mark attendance',false);
  const date=$('#attDate').value;
  const subject_id=$('#attSubject')?.value||null;
  const session_name=$('#attSession')?.value||'';
  const entries=[...document.querySelectorAll('.attStatus')].map(sel=>({student_id: parseInt(sel.dataset.id), status: sel.value, leave_reason: document.querySelector(`[data-reason="${sel.dataset.id}"]`)?.value||'', time: document.querySelector(`[data-time="${sel.dataset.id}"]`)?.value||''})).filter(e=>e.status);
  if(!entries.length) return toast('Select at least one status',false);
  const payload={date,entries,subject_id:subject_id?parseInt(subject_id):null,session:session_name};
  if(!navigator.onLine){
    const q=JSON.parse(localStorage.getItem('attQueue')||'[]');
    q.push(payload);
    localStorage.setItem('attQueue',JSON.stringify(q));
    toast('Offline — saved locally, will sync ✅');
    return;
  }
  try{ const r=await api('/api/attendance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); toast(`Attendance saved ✅ (${r.saved||entries.length})`); loadAttendance(); loadNotifBadge(); }catch(e){toast(e.message,false)}
}
async function completeAttendance(){ if(!['admin','teacher'].includes(state.role)) return toast('Access denied',false); await saveAttendance(); const date=$('#attDate').value; const d=await api('/api/attendance/dashboard?date='+date).catch(()=>({present:298,total:320,percentage:93,absent:12,leave:10})); const text=`Attendance ${date} — Present: ${d.present}/${d.total} (${d.percentage}%) Absent:${d.absent} Leave:${d.leave} — Green Valley High School 🇮🇳`; window.open(`https://wa.me/?text=${encodeURIComponent(text)}`,'_blank'); toast('WhatsApp prepared'); }
async function scanAttendance(){ if(!['admin','teacher'].includes(state.role)) return toast('Access denied',false); try { if (window.Capacitor) { const image = await Capacitor.Plugins.Camera.getPhoto({ quality: 90, allowEditing: false, resultType: 'base64' }); toast('Photo captured via Capacitor Camera API'); } const code=document.querySelector('#scanCode').value.trim(), status=document.querySelector('#scanStatus').value, date=document.querySelector('#attDate').value; if(!code) return toast('Enter Student ID',false); await api('/api/attendance/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,status,date})}); toast('Marked '+status+' ?'); loadAttendance(); const ss=document.querySelector('#scanSuccess'); if(ss) ss.classList.remove('hidden'); }catch(e){toast(e.message,false)} }

// MONTHLY
function initMonthly(){ const el=$('#monMonth'); if(el && !el.value) el.value=new Date().toISOString().slice(0,7); loadMonthly(); }
async function loadMonthly(){
  const month=$('#monMonth').value, cid=$('#monClass').value, sid=$('#monSection').value;
  if(!month) return toast('Select month',false);
  let data; try{ data=await api(`/api/monthly?month=${month}&class_id=${cid}&section_id=${sid}`); }catch(e){ toast(e.message,false); return; }
  if(!data){ return; }
  const monStats=$('#monStats'); if(monStats) monStats.innerHTML=`
    <div class="stat-card blue"><div class="stat-icon">${icon('graduation-cap')}</div><div><small>Total Students</small><b>${data.students.length}</b></div></div>
    <div class="stat-card green"><div class="stat-icon">${icon('circle-check')}</div><div><small>Avg Present</small><b>${Math.round(data.students.reduce((a,c)=>a+c.present,0)/Math.max(1,data.students.length))}</b></div></div>
    <div class="stat-card red"><div class="stat-icon">${icon('calendar')}</div><div><small>Working Days</small><b>${data.working_days}</b></div></div>
    <div class="stat-card yellow"><div class="stat-icon">${icon('table-2')}</div><div><small>Month</small><b>${month}</b></div></div>`;
  const monTable=$('#monTable');
  if(monTable) monTable.innerHTML=`<table><thead><tr><th>Photo</th><th>Student Name</th><th>Present</th><th>Absent</th><th>Leave</th><th>%</th></tr></thead><tbody>`+data.students.map(s=>`<tr><td><img src="https://ui-avatars.com/api/?name=${encodeURIComponent(s.student.name)}&background=2563eb&color=fff&size=32" class="avatar"></td><td><b>${s.student.name}</b><br><small>${s.student.student_id} • ${s.student.roll_no||''}</small></td><td><span class="badge P">${s.present}</span></td><td><span class="badge A">${s.absent}</span></td><td><span class="badge L">${s.leave}</span></td><td><span class="badge ${s.pct>=90?'P':s.pct>=75?'L':'A'}">${s.pct}%</span></td></tr>`).join('')+`</tbody></table>`;
  const monInfo=$('#monInfo'); if(monInfo) monInfo.textContent=`Working Days: ${data.working_days} — ${data.working_dates.slice(0,3).join(', ')} ...`;
}
function exportMonthly(type){ const month=$('#monMonth').value; if(!month) return toast('Select month',false); const cid=$('#monClass').value, sid=$('#monSection').value; window.open(`/api/export/monthly/${type}?month=${month}&class_id=${cid}&section_id=${sid}`,'_blank'); }

// HOLIDAYS / STAFF etc
async function loadHolidays(){ let data; try{ data=await api('/api/holidays'); }catch(e){ data=[]; } const el=$('#holidayTable'); if(!el) return; el.innerHTML=data.length? `<table><thead><tr><th>Date</th><th>Name</th><th>Type</th><th></th></tr></thead><tbody>`+data.map(h=>`<tr><td>${h.date} <small>(${new Date(h.date).toLocaleDateString('en-IN',{weekday:'short'})})</small></td><td>${h.name}</td><td><span class="pill">${h.type}</span></td><td>${state.role==='admin'?`<button class="btn-red" onclick="delHoliday(${h.id})">Delete</button>`:''}</td></tr>`).join('')+`</tbody></table>` : `<div class="muted" style="padding:16px">No holidays yet. Sundays are auto-holidays.</div>`; }
async function addHoliday(){ if(state.role!=='admin') return toast('Admin only',false); const date=$('#holDate').value, name=$('#holName').value.trim(), type=$('#holType').value; if(!date||!name) return toast('Date & name required',false); try{await api('/api/holidays',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date,name,type})}); loadHolidays(); toast('Holiday added');}catch(e){toast(e.message,false)} }
async function delHoliday(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/holidays?id='+id,{method:'DELETE'}); loadHolidays(); toast('Deleted');}catch(e){toast(e.message,false)} }

async function loadStaff(){ let data; try{ data=await api('/api/staff'); }catch(e){ data=[]; } const demo=data.length? data : (state.role==='admin'? [{name:'Mr. Sharma', role:'Mathematics', phone:'9876543210', id:1},{name:'Ms. Gupta', role:'Science', phone:'9876543211', id:2}] : []); const el=$('#staffGrid'); if(!el) return; if(!data.length && state.role!=='admin'){ el.innerHTML=`<div class="muted" style="padding:16px">🔒 Admin only</div>`; return; } el.innerHTML=demo.map(s=>`<div class="staff-card"><img src="https://i.pravatar.cc/100?img=${(s.id%70)+1}"><h4>${s.name}</h4><p class="muted">${s.role}</p><p class="pill" style="background:#eef2ff">${s.phone||''}</p><div style="margin-top:8px;display:flex;gap:6px;justify-content:center">${state.role==='admin'?`<button class="btn-outline" onclick="delStaff(${s.id})">Remove</button>`:''}<button class="btn-outline">Permissions</button></div><small class="badge P" style="margin-top:6px;display:inline-block">Active</small></div>`).join(''); }
async function addStaff(){ if(state.role!=='admin') return toast('Admin only',false); const name=$('#staffName').value.trim(), role=$('#staffRole').value.trim(), phone=$('#staffPhone').value.trim(); if(!name||!role) return toast('Name & role required',false); try{await api('/api/staff',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,role,phone})}); loadStaff(); toast('Staff added');}catch(e){toast(e.message,false)} }
async function delStaff(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/staff?id='+id,{method:'DELETE'}); loadStaff(); toast('Removed');}catch(e){toast(e.message,false)} }
async function loadParents(){
  let data; try{ data=await api('/api/parents'); }catch(e){ data=[]; }
  const el=$('#parentsTable'); if(!el) return;
  if(state.role!=='admin'){ el.innerHTML=`<div class="muted" style="padding:16px">🔒 Admin only — Parents: ${data.length} linked</div>`; return; }
  el.innerHTML=data.length? `<table><thead><tr><th>Name</th><th>Phone</th><th>Email</th><th>Student</th><th></th></tr></thead><tbody>`+data.map(p=>`<tr><td>${p.name}</td><td>${p.phone||''}</td><td>${p.email||''}</td><td>${p.student_name||p.student_id||''}</td><td><button class="btn-red" onclick="delParent(${p.id})">Delete</button></td></tr>`).join('')+`</tbody></table>` : `<div class="muted" style="padding:16px">No parents yet. Add via + Add Parent.</div>`;
  // populate student select for modal
  try{
    const studs=await api('/api/students');
    const sel=$('#parStudent'); if(sel) sel.innerHTML=studs.map(s=>`<option value="${s.id}">${s.name} (${s.student_id})</option>`).join('');
    const sel2=$('#parStudentModal'); if(sel2) sel2.innerHTML=studs.map(s=>`<option value="${s.id}">${s.name} (${s.student_id})</option>`).join('');
  }catch(e){}
}
async function addParent(){
  if(state.role!=='admin') return toast('Admin only',false);
  const name=$('#parName').value.trim(), phone=$('#parPhone').value.trim(), email=$('#parEmail').value.trim();
  const sid=$('#parStudentModal')?.value || $('#parStudent')?.value;
  if(!name) return toast('Name required',false);
  try{ await api('/api/parents',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,phone,email,student_id:sid})}); loadParents(); toast('Parent added'); }catch(e){ toast(e.message,false); }
}
async function delParent(id){ if(state.role!=='admin') return toast('Admin only',false); try{ await api('/api/parents?id='+id,{method:'DELETE'}); loadParents(); toast('Removed'); }catch(e){ toast(e.message,false); } }
async function loadWhatsApp(){ let data; try{ data=await api('/api/whatsapp'); }catch(e){ data=[]; } const el=$('#waList'); if(!el) return; el.innerHTML=data.length? `<table><thead><tr><th>Class</th><th>Section</th><th>Link</th></tr></thead><tbody>`+data.map(w=>`<tr><td>${w.class_name||w.class_id}</td><td>${w.section_name||w.section_id}</td><td><a href="${w.link}" target="_blank">${w.link}</a></td></tr>`).join('')+`</tbody></table>` : `<div class="muted" style="padding:16px">No WhatsApp groups yet.</div>`; }
async function saveWhatsApp(){ if(!['admin','teacher'].includes(state.role)) return toast('Access denied',false); const c=$('#waClass').value, s=$('#waSection').value, link=$('#waLink').value.trim(); if(!c||!s||!link) return toast('All fields required',false); try{await api('/api/whatsapp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class_id:c,section_id:s,link})}); loadWhatsApp(); toast('Group saved');}catch(e){toast(e.message,false)} }

let _dsTab='upcoming';
function setDsTab(t){
  _dsTab=t;
  document.querySelectorAll('#dsTabs button').forEach(b=>b.classList.toggle('active', b.dataset.ds===t));
  renderDateSheets();
}
async function loadDateSheets(){
  const el=$('#dsTable'); if(!el) return;
  el.innerHTML='<div class="sk-wrap"><div class="sk sk-row"></div><div class="sk sk-row"></div><div class="sk sk-row"></div></div>';
  let data;
  try{
    data = (state.role==='student'||state.role==='parent')
      ? ((await api('/api/portal/datesheet'+(childQs()?'?'+childQs().slice(1):''))).datesheet||[])
      : await api('/api/datesheets');
  }catch(e){ data=[]; }
  window._dsData=Array.isArray(data)?data:[];
  renderDateSheets();
}
function renderDateSheets(){
  const el=$('#dsTable'); if(!el) return;
  const all=(window._dsData||[]);
  const today=new Date().toISOString().slice(0,10);
  const rows=all.filter(d=>_dsTab==='upcoming' ? d.date>=today : d.date<today)
                .sort((a,b)=> _dsTab==='upcoming' ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date));
  const cnt=$('#dsCount'); if(cnt) cnt.textContent=rows.length+' exam'+(rows.length===1?'':'s');
  const sub=$('#dsSub');
  if(sub) sub.textContent = (state.role==='student'||state.role==='parent')
    ? 'Check your upcoming examination dates' : 'Manage examination schedules per class';
  const staff=state.role==='admin';
  if(!rows.length){
    el.innerHTML='<div class="card empty"><div class="eic">'+icon('calendar-days')+'</div><h4>No '+_dsTab+' exams</h4><p>'+(staff?'Add an exam from the form above.':'The exam schedule will appear here once the school publishes it.')+'</p></div>';
    return;
  }
  el.innerHTML=rows.map(d=>{
    const dt=new Date(d.date+'T00:00:00');
    const day=isNaN(dt)?'':dt.getDate();
    const mon=isNaN(dt)?'':dt.toLocaleDateString('en-IN',{month:'short'});
    const weekday=isNaN(dt)?'':dt.toLocaleDateString('en-IN',{weekday:'short'});
    const past=d.date<today;
    return `<div class="ds-row"${past?' style="opacity:.62"':''}>
      <div class="ds-date"><b>${day}</b><span>${mon}</span><small>${weekday}</small></div>
      <div class="db">
        <b>${esc(d.subject)}</b>
        <span>${esc(d.exam_type)} • Class ${esc(d.class_name||d.class_id)}</span>
        <div class="meta" style="margin-top:5px;font-size:11px;color:var(--muted)">${d.time?'<span class="pill n">'+esc(d.time)+'</span>':''}${past?'<span class="pill">Completed</span>':'<span class="pill g">Upcoming</span>'}</div>
      </div>
      <div class="row-actions">${staff?`<button type="button" class="danger" onclick="delDS(${d.id})">${icon('trash-2')} Delete</button>`:''}</div>
    </div>`;
  }).join('');
}
async function addDateSheet(){ if(state.role!=='admin') return toast('Admin only',false); const class_id=$('#dsClass').value, exam_type=$('#dsExam').value, subject=$('#dsSubject').value.trim(), date=$('#dsDate').value, time=$('#dsTime').value; if(!class_id||!subject||!date) return toast('Class, subject, date required',false); try{await api('/api/datesheets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class_id,exam_type,subject,date,time})}); loadDateSheets(); toast('Added');}catch(e){toast(e.message,false)} }
async function delDS(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/datesheets?id='+id,{method:'DELETE'}); loadDateSheets();}catch(e){toast(e.message,false)} }

async function initMarksChips(){ let subs; try{ subs=await api('/api/subjects'); }catch(e){ subs=[]; } const el=$('#subjectChips'); if(!el) return; el.innerHTML=subs.map(s=>`<span class="pill" style="background:#eef2ff">${s.name} ${state.role==='admin'?`<a href="#" onclick="delSubject(${s.id});return false" style="color:var(--red)">✕</a>`:''}</span>`).join(''); }
async function addSubject(){ if(state.role!=='admin') return toast('Admin only',false); const n=$('#newSubject').value.trim(); if(!n) return; try{await api('/api/subjects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})}); $('#newSubject').value=''; initMarksChips(); toast('Subject added');}catch(e){toast(e.message,false)} }
async function delSubject(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/subjects?id='+id,{method:'DELETE'}); initMarksChips();}catch(e){toast(e.message,false)} }
async function loadMarksReport(){ const cid=$('#repClass')?.value||'', exam=$('#repExam')?.value||'Mid-Term'; let data; try{ data=await api(`/api/marks/report?class_id=${cid}&exam_type=${encodeURIComponent(exam)}`); }catch(e){ toast(e.message,false); return; } const subs=await api('/api/subjects').catch(()=>[]); if(!data.length){ const el=$('#marksReport'); if(el) el.innerHTML=`<div class="muted" style="padding:16px">No marks yet for ${exam}.</div>`; return; } const canManage = ['admin','teacher'].includes(state.role); const el=$('#marksReport'); if(el) el.innerHTML=`<table><thead><tr><th>Roll</th><th>Student</th><th>Marks</th><th>Total</th><th>%</th><th></th></tr></thead><tbody>`+data.map(d=>`<tr><td>${d.student.roll_no||''}</td><td><b>${d.student.name}</b><br><small>${d.student.student_id}</small></td><td>${d.marks.map(m=>`${m.subject_name}:${m.obtained}/${m.max_marks}`).join(', ')||'—'}</td><td>${d.total_obt}/${d.total_max}</td><td><span class="badge ${d.pct>=90?'P':d.pct>=60?'L':'A'}">${d.pct}%</span></td><td>${canManage?`<button class="btn-outline" onclick="openMarksEntry(${d.student.id},'${d.student.name.replace(/'/g,"")}','${exam}')">Enter</button>`:''}</td></tr>`).join('')+`</tbody></table>`; window._subs=subs; }
let _curMarks=null,_curExam=null;
async function openMarksEntry(sid,name,exam){ if(!['admin','teacher'].includes(state.role)) return toast('Access denied',false); _curMarks=sid; _curExam=exam; const elN=$('#marksStudentName'); if(elN) elN.textContent=name+' — '+exam; const me=$('#marksEntry'); if(me) me.classList.remove('hidden'); const subs=window._subs||await api('/api/subjects'); let ex; try{ ex=await api(`/api/marks?student_id=${sid}&exam_type=${encodeURIComponent(exam)}`); }catch(e){ ex=[]; } const map={}; ex.forEach(m=>map[m.subject_id]=m); const inp=$('#marksInputs'); if(inp) inp.innerHTML=subs.map(s=>`<div style="display:flex;gap:8px;align-items:center;margin:6px 0"><span style="min-width:120px">${s.name}</span><input type="number" data-max="max-${s.id}" value="${map[s.id]?.max_marks||100}" style="width:80px;padding:6px;border:1px solid #e2e8f0;border-radius:8px"><input type="number" data-obt="${s.id}" value="${map[s.id]?.obtained||''}" placeholder="Obtained" style="width:80px;padding:6px;border:1px solid #e2e8f0;border-radius:8px"></div>`).join(''); }
async function saveMarks(){ if(!['admin','teacher'].includes(state.role)) return toast('Access denied',false); const marks=[...document.querySelectorAll('[data-obt]')].map(i=>{const sid=i.getAttribute('data-obt'); const obt=parseInt(i.value); if(isNaN(obt)) return null; const max=parseInt(document.querySelector(`[data-max="max-${sid}"]`).value)||100; return {subject_id:parseInt(sid), max_marks:max, obtained:obt}}).filter(Boolean); if(!marks.length) return toast('Enter marks',false); try{await api('/api/marks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({student_id:_curMarks, exam_type:_curExam, marks})}); toast('Marks saved'); loadMarksReport(); const me=$('#marksEntry'); if(me) me.classList.add('hidden');}catch(e){toast(e.message,false)} }

function showQRFor(id){ if(!['admin','teacher'].includes(state.role) && state.role!=='admin') { /* student can view own QR only */ if(state.role==='student' && state.currentUser?.linked_student_id){ /* allow */ } } navigate('qr'); const el=$('#qrStudentId'); if(el) el.value=id; showQR(); }
async function showQR(){ const id=$('#qrStudentId').value.trim(); if(!id) return toast('Enter Student ID',false); const disp=$('#qrDisplay'); if(!disp) return; disp.innerHTML=`<img src="${BACKEND_URL}/api/students/${id}/qr" style="width:220px;height:220px;border-radius:12px;border:1px solid #e2e8f0;padding:8px;background:#fff"><p><b>${id}</b></p><p class="muted sm">Scan with camera to mark attendance</p><button class="btn-outline" onclick="window.open('${BACKEND_URL}/api/students/${id}/qr')">Download PNG</button><div class="scan-success" style="margin-top:8px;background:#dcfce7;color:#166534;padding:8px;border-radius:8px">✅ QR Ready — Scan Successful</div>`; }

async function loadNotices(){
  const el=$('#noticeList'); if(!el) return;
  el.innerHTML='<div class="sk-wrap"><div class="sk sk-card"></div><div class="sk sk-card"></div></div>';
  let data; try{ data=await api('/api/notices'); }catch(e){ data=[]; }
  const cnt=$('#noticeCount'); if(cnt) cnt.textContent=(data?data.length:0)+' notice'+((data&&data.length)===1?'':'s');
  el.innerHTML = data.length ? data.map(n=>`<div class="notice-card">
      <b>${esc(n.title)}</b>
      <p class="muted">${esc(n.content)}</p>
      <div class="meta"><span>${icon('calendar')} ${esc(n.date||'')}</span>
        ${state.role==='admin'?`<span class="row-actions"><button type="button" class="danger" onclick="delNotice(${n.id})">${icon('trash-2')} Delete</button></span>`:''}
      </div>
    </div>`).join('')
    : `<div class="card empty"><div class="eic">${icon('megaphone')}</div><h4>No notices yet</h4><p>School announcements and circulars will appear here.</p></div>`;
}
async function addNotice(){ if(state.role!=='admin') return toast('Admin only',false); const t=$('#noticeTitle').value.trim(), c=$('#noticeContent').value.trim(); if(!t) return toast('Title required',false); try{await api('/api/notices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,content:c})}); loadNotices(); toast('Notice posted');}catch(e){toast(e.message,false)} }
async function delNotice(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/notices?id='+id,{method:'DELETE'}); loadNotices();}catch(e){toast(e.message,false)} }

let _enoteData=[], _enoteSubject='';
function _isUrl(u){ return /^(https?:)?\/\//i.test(String(u||'').trim()); }
function escAttr(s){ return String(s??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function esc(s){ return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
async function loadENotes(){
  const el=$('#enoteList'); if(!el) return;
  el.innerHTML='<div class="sk-wrap"><div class="sk sk-row"></div><div class="sk sk-row"></div><div class="sk sk-row"></div></div>';
  try{ _enoteData=await api('/api/enotes'); }catch(e){ _enoteData=[]; }
  renderENoteSubjects();
  filterENotes();
}
function renderENoteSubjects(){
  const box=$('#noteSubjectChips'); if(!box) return;
  const subs=[...new Set(_enoteData.map(n=>(n.subject||'').trim()).filter(Boolean))];
  box.innerHTML=['<button type="button" class="chip'+(_enoteSubject===''?' active':'')+'" onclick="setENoteSubject(\'\')">All</button>']
    .concat(subs.map(s=>`<button type="button" class="chip${_enoteSubject===s?' active':''}" onclick="setENoteSubject('${escAttr(s)}')">${esc(s)}</button>`)).join('');
}
function setENoteSubject(s){ _enoteSubject=s; renderENoteSubjects(); filterENotes(); }
function filterENotes(){
  const el=$('#enoteList'); if(!el) return;
  const q=($('#noteQ')?.value||'').toLowerCase().trim();
  const rows=_enoteData.filter(n=>{
    const okSub=!_enoteSubject || (n.subject||'').trim()===_enoteSubject;
    const hay=(n.title+' '+(n.subject||'')+' '+(n.content||'')+' '+(n.teacher_name||'')).toLowerCase();
    return okSub && (!q || hay.includes(q));
  });
  const cnt=$('#enoteCount'); if(cnt) cnt.textContent=rows.length+' note'+(rows.length===1?'':'s');
  const staff=['admin','teacher'].includes(state.role);
  if(!rows.length){
    el.innerHTML='<div class="card empty"><div class="eic">'+icon('book-open')+'</div><h4>'+(q||_enoteSubject?'No matching notes':'No e-notes yet')+'</h4><p>'+(staff?'Upload the first note for your students.':'Teachers have not shared any notes yet. Check back soon.')+'</p></div>';
    return;
  }
  el.innerHTML=rows.map((n,i)=>{
    const cls=['','green','purple','yellow'][i%4];
    const url=_isUrl(n.content);
    const actions=[
      url?`<button type="button" onclick="openENote(${n.id})">${icon('arrow-right')} Open</button>`:'',
      url?`<button type="button" onclick="downloadENote(${n.id})">${icon('download')} Download</button>`
         :`<button type="button" onclick="copyENote(${n.id})">${icon('files')} Copy</button>`,
      staff?`<button type="button" class="danger" onclick="delENote(${n.id})">${icon('trash-2')} Delete</button>`:''
    ].join('');
    return `<div class="note-card">
      <div class="nf ${cls}">${icon(url?'file-down':'file-text')}</div>
      <div class="nb">
        <b>${esc(n.title)}</b>
        <div class="sub">${esc(n.content||'')}</div>
        <div class="meta">${n.subject?`<span class="pill n">${esc(n.subject)}</span>`:''}
          <span>${esc(n.date||'')}</span>
          ${n.teacher_name?`<span>${esc(n.teacher_name)}</span>`:''}</div>
      </div>
      <div class="row-actions">${actions}</div>
    </div>`;
  }).join('');
}
function _enoteById(id){ return _enoteData.find(n=>n.id===id); }
function openENote(id){ const n=_enoteById(id); if(!n) return; if(_isUrl(n.content)) window.open(n.content,'_blank','noopener'); else toast('This note has no downloadable link'); }
function downloadENote(id){
  const n=_enoteById(id); if(!n||!_isUrl(n.content)) return;
  const a=document.createElement('a'); a.href=n.content; a.target='_blank'; a.rel='noopener';
  a.download=(n.title||'e-note').replace(/[^\w\- ]+/g,'').trim().replace(/\s+/g,'-')+'.txt';
  document.body.appendChild(a); a.click(); a.remove();
  toast('Download started');
}
function copyENote(id){
  const n=_enoteById(id); if(!n) return;
  const text=n.title+(n.subject?' ('+n.subject+')':'')+'\n'+(n.content||'');
  if(navigator.clipboard?.writeText){ navigator.clipboard.writeText(text).then(()=>toast('Note copied')).catch(()=>toast('Copy failed',false)); }
  else toast('Copying is not supported on this device',false);
}
async function addENote(){ if(!['admin','teacher'].includes(state.role)) return toast('Access denied: cannot add notes',false); const t=$('#noteTitle').value.trim(), s=$('#noteSubject').value.trim(), c=$('#noteContent').value.trim(); if(!t) return toast('Title required',false); if(!s) return toast('Subject required',false); if(!c) return toast('Content or link required',false); try{await api('/api/enotes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,subject:s,content:c})}); ['#noteTitle','#noteSubject','#noteContent'].forEach(x=>{const e2=$(x); if(e2) e2.value='';}); loadENotes(); toast('Note uploaded');}catch(e){toast(e.message,false)} }
async function delENote(id){ if(!['admin','teacher'].includes(state.role)) return toast('Access denied',false); try{await api('/api/enotes?id='+id,{method:'DELETE'}); loadENotes();}catch(e){toast(e.message,false)} }

async function loadMeals(){ let data; try{ data=await api('/api/meals'); }catch(e){ data=[]; } const el=$('#mealTable'); if(!el) return; el.innerHTML=data.length? `<table><thead><tr><th>Date</th><th>Class</th><th>Count</th><th>Menu</th><th></th></tr></thead><tbody>`+data.map(m=>`<tr><td>${m.date}</td><td>${m.class_id||''}</td><td>${m.count}</td><td>${m.menu}</td><td>${state.role==='admin'?`<button class="btn-red" onclick="delMeal(${m.id})">Delete</button>`:''}</td></tr>`).join('')+`</tbody></table>` : `<div class="muted" style="padding:16px">No meals</div>`; }
async function addMeal(){ if(state.role!=='admin') return toast('Admin only',false); const date=$('#mealDate').value||new Date().toISOString().slice(0,10), class_id=$('#mealClass').value||null, count=$('#mealCount').value, menu=$('#mealMenu').value; if(!count) return toast('Count required',false); try{await api('/api/meals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date,class_id,count,menu})}); loadMeals(); toast('Meal added');}catch(e){toast(e.message,false)} }
async function delMeal(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/meals?id='+id,{method:'DELETE'}); loadMeals();}catch(e){toast(e.message,false)} }

async function loadScholarships(){ let data; try{ data=await api('/api/scholarships'); }catch(e){ data=[]; } const el=$('#schTable'); if(!el) return; el.innerHTML=data.length? `<table><thead><tr><th>Student</th><th>Scheme</th><th>Amount</th><th>Status</th><th></th></tr></thead><tbody>`+data.map(s=>`<tr><td>${s.student_name} (${s.sid})</td><td>${s.scheme}</td><td>${s.amount||''}</td><td><span class="pill g">${s.status}</span></td><td>${state.role==='admin'?`<button class="btn-red" onclick="delSch(${s.id})">Delete</button>`:''}</td></tr>`).join('')+`</tbody></table>` : `<div class="muted" style="padding:16px">No scholarships</div>`; }
async function addScholarship(){ if(state.role!=='admin') return toast('Admin only',false); const sid=$('#schStudent').value, scheme=$('#schScheme').value.trim(), amount=$('#schAmount').value, status=$('#schStatus').value; if(!sid||!scheme) return toast('Select student & scheme',false); try{await api('/api/scholarships',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({student_id:sid,scheme,amount,status})}); loadScholarships(); toast('Added');}catch(e){toast(e.message,false)} }
async function delSch(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/scholarships?id='+id,{method:'DELETE'}); loadScholarships();}catch(e){toast(e.message,false)} }

async function loadComplaints(){ let data; try{ data=await api('/api/complaints'); }catch(e){ data=[]; } const el=$('#compTable'); if(!el) return; el.innerHTML=data.length? `<table><thead><tr><th>Name</th><th>Complaint</th><th>Status</th><th>Date</th><th></th></tr></thead><tbody>`+data.map(c=>`<tr><td>${c.name||''}</td><td>${c.text}</td><td><span class="pill ${c.status==='Open'?'r':'g'}">${c.status}</span></td><td>${c.date}</td><td>${state.role==='admin'?`<button class="btn-green" onclick="updComp(${c.id},'Resolved')">Resolve</button> <button class="btn-red" onclick="delComp(${c.id})">Delete</button>`:''}</td></tr>`).join('')+`</tbody></table>` : `<div class="muted" style="padding:16px">No complaints</div>`; }
async function addComplaint(){ const n=$('#compName').value.trim(), t=$('#compText').value.trim(); if(!t) return; try{await api('/api/complaints',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,text:t})}); loadComplaints(); toast('Submitted');}catch(e){toast(e.message,false)} }
async function delComp(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/complaints?id='+id,{method:'DELETE'}); loadComplaints();}catch(e){toast(e.message,false)} }
async function updComp(id,s){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/complaints?id='+id+'&status='+s,{method:'DELETE'}); loadComplaints();}catch(e){toast(e.message,false)} }

async function loadSettings(){
  let s; try{ s=await api('/api/settings'); }catch(e){ s={}; }
  const name=s.school_name||'Green Valley High School';
  const color=s.branding_color||'#2563eb';
  const addrEl=$('#setAddress'), contEl=$('#setContact');
  if($('#setSchoolName')) $('#setSchoolName').value=name;
  if($('#setColor')) $('#setColor').value=color;
  if(addrEl) addrEl.value=s.address||'';
  if(contEl) contEl.value=s.contact||'';
  const tsName=$('#topSchoolName');
  if(tsName) tsName.textContent=name;
  const brandSub=document.querySelector('.brand-sub');
  if(brandSub) brandSub.textContent=name;
  const brandTitle=document.querySelector('.brand-title');
  if(brandTitle) brandTitle.textContent='Dynamic CuroBase';
  const si=$('#schoolInfo'); if(si) si.innerHTML=`<b>${esc(name)}</b> • Govt. Recognised • ${s.total_classes||12} Classes`;
  const acctName=$('#setName'); if(acctName) acctName.textContent=(typeof portalAccountName==='function'?portalAccountName():state.currentUser?.username)||'–';
  const acctRole=$('#setRole'); if(acctRole) acctRole.textContent=state.role||'–';
  const acctUser=$('#setUsername'); if(acctUser) acctUser.textContent=state.currentUser?.username||'–';
  const sidebarLogo=document.getElementById('sidebarLogo');
  const topbarLogo=document.getElementById('topbarLogo');
  const logoPrev=$('#logoPreview');
  if(s.logo_path){
    const url=`${BACKEND_URL}/api/logo/${s.logo_path}?t=${Date.now()}`;
    if(sidebarLogo) sidebarLogo.innerHTML=`<img src="${url}" alt="logo">`;
    if(topbarLogo){ topbarLogo.classList.remove('hidden'); const img=topbarLogo.querySelector('img'); if(img) img.src=url; }
    if(logoPrev) logoPrev.innerHTML=`<img src="${url}"> <div><b>${s.logo_path}</b><br><small class="muted">${name}</small></div>`;
  } else {
    if(sidebarLogo) sidebarLogo.innerHTML=icon('graduation-cap');
    if(topbarLogo) topbarLogo.classList.add('hidden');
    if(logoPrev) logoPrev.innerHTML=`<span class="muted">No logo uploaded — shows the default mark</span>`;
  }
  let perms; try{ perms=await api('/api/permissions'); }catch(e){ perms=[]; } const pg=$('#permGrid'); if(pg) pg.innerHTML=perms.map(p=>`<label style="display:flex;gap:6px;align-items:center"><input type="checkbox" checked> ${p}</label>`).join(''); let users=[], hist=[]; if(state.role==='admin'){ try{ users=await api('/api/users'); }catch(e){ users=[]; } try{ hist=await api('/api/login_history'); }catch(e){ hist=[]; } } const ut=$('#userTable'); if(ut){ if(state.role!=='admin'){ ut.innerHTML=`<div class="muted">🔒 Admin only</div>`; } else { ut.innerHTML=users.length? `<table><thead><tr><th>User</th><th>Role</th><th></th></tr></thead><tbody>`+users.map(u=>`<tr><td>${u.username}</td><td>${u.role}</td><td><button class="btn-red" onclick="delUser(${u.id})">Delete</button></td></tr>`).join('')+`</tbody></table>` : `No users`; } } const lh=$('#loginHistory'); if(lh){ if(state.role!=='admin'){ lh.innerHTML=`<div class="muted">🔒 Admin only</div>`; } else { lh.innerHTML=hist.length? `<table><thead><tr><th>User</th><th>Time</th><th>OK</th></tr></thead><tbody>`+hist.map(h=>`<tr><td>${h.username}</td><td>${h.time}</td><td>${h.success?'✅':'❌'}</td></tr>`).join('')+`</tbody></table>` : `No history`; } }
  // hide mutating settings actions for non-admin (the backend rejects them regardless)
  document.querySelectorAll('#view-settings .admin-only, #classToolbar, #noticeToolbar').forEach(b=>{
    b.classList.toggle('hidden', state.role!=='admin');
  });
  const dm=$('#setDarkMode'); if(dm) dm.checked = document.documentElement.getAttribute('data-theme')==='dark';
  const rm=$('#setReduceMotion'); if(rm) rm.checked = document.documentElement.hasAttribute('data-reduce-motion');
}
async function saveSettings(){
  if(state.role!=='admin') return toast('Admin only',false);
  const name=$('#setSchoolName')?.value?.trim();
  const color=$('#setColor')?.value;
  const address=$('#setAddress')?.value?.trim()||'';
  const contact=$('#setContact')?.value?.trim()||'';
  if(!name) return toast('School name required',false);
  try{ await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({school_name:name, branding_color:color, address, contact})}); toast('Settings saved ✅ '+name); await loadSettings(); }catch(e){ toast(e.message,false); }
}
function previewLogo(input){
  const f=input.files[0];
  const box=document.getElementById('logoLocalPreview');
  const img=document.getElementById('logoLocalImg');
  if(!f){ box?.classList.add('hidden'); return; }
  if(f.size>2*1024*1024) return toast('Max 2MB',false);
  if(!['image/png','image/jpeg','image/webp','image/jpg'].includes(f.type)) return toast('PNG/JPG/WebP only',false);
  const url=URL.createObjectURL(f);
  if(img) img.src=url;
  box?.classList.remove('hidden');
}
async function uploadLogo(){
  if(state.role!=='admin') return toast('Admin only',false);
  const f=$('#logoFile')?.files[0];
  if(!f) return toast('Choose file first',false);
  if(f.size>2*1024*1024) return toast('File too large — max 2MB',false);
  const fd=new FormData(); fd.append('logo',f);
  const r=await fetch(BACKEND_URL + '/api/settings/logo',{method:'POST',body:fd,credentials:'same-origin'});
  const j=await r.json().catch(()=>({}));
  if(!r.ok) return toast(j.error||'Upload failed',false);
  toast('Logo uploaded ✅');
  const lp=document.getElementById('logoLocalPreview'); if(lp) lp.classList.add('hidden');
  const lf=$('#logoFile'); if(lf) lf.value='';
  await loadSettings();
}
async function removeLogo(){
  if(state.role!=='admin') return toast('Admin only',false);
  if(!confirm('Remove logo?')) return;
  try{ await api('/api/settings/logo',{method:'DELETE'}); toast('Logo removed'); await loadSettings(); }catch(e){ toast(e.message,false); }
}
async function addUser(){ if(state.role!=='admin') return toast('Admin only',false); const u=$('#uName').value.trim(), p=$('#uPass').value, r=$('#uRole').value; if(!u||!p) return toast('Required',false); try{await api('/api/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p,role:r,permissions:[]})}); loadSettings(); toast('User created');}catch(e){toast(e.message,false)} }
async function delUser(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/users?id='+id,{method:'DELETE'}); loadSettings();}catch(e){toast(e.message,false)} }
// ---- TEACHERS ----
async function loadTeachers(){
  let data; try{ data=await api('/api/teachers'); }catch(e){ data=[]; }
  const q=($('#t_q')?.value||'').toLowerCase();
  if(q) data=data.filter(t=>(t.name+' '+(t.email||'')+' '+(t.subject||'')).toLowerCase().includes(q));
  const el=$('#teachersTable'); if(!el) return;
  if(state.role!=='admin'){ el.innerHTML=`<div class="muted" style="padding:16px">🔒 Admin only</div>`; return; }
  el.innerHTML=data.length? `<table><thead><tr><th>Teacher ID</th><th>Name</th><th>Email</th><th>Phone</th><th>Subject</th><th>Assigned Class</th><th></th></tr></thead><tbody>`+data.map(t=>`<tr><td>TCH-${t.id}</td><td><b>${t.name}</b></td><td>${t.email||''}</td><td>${t.phone||''}</td><td>${t.subject||''}</td><td>${t.assigned_class||''}</td><td><button class="btn-red" onclick="delTeacher(${t.id})">Delete</button></td></tr>`).join('')+`</tbody></table>` : `<div class="muted" style="padding:16px">No teachers yet.</div>`;
}
async function addTeacher(){
  if(state.role!=='admin') return toast('Admin only',false);
  const name=$('#t_name').value.trim(); if(!name) return toast('Name required',false);
  const payload={name, email:$('#t_email').value.trim(), phone:$('#t_phone').value.trim(), subject:$('#t_subject').value.trim(), assigned_class:$('#t_class').value.trim()};
  try{ await api('/api/teachers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); loadTeachers(); toast('Teacher added ✅'); }catch(e){ toast(e.message,false); }
}
async function delTeacher(id){ if(state.role!=='admin') return toast('Admin only',false); if(!confirm('Delete teacher?')) return; try{ await api('/api/teachers?id='+id,{method:'DELETE'}); loadTeachers(); }catch(e){ toast(e.message,false); } }
// ---- CALENDAR ----
function initCalendar(){ const el=$('#calMonth'); if(el && !el.value) el.value=new Date().toISOString().slice(0,7); loadCalendar(); }
async function loadCalendar(){
  const month=$('#calMonth').value, cid=$('#calClass')?.value||'', sid=$('#calSection')?.value||'';
  if(!month) return toast('Select month',false);
  let data; try{ data=await api(`/api/calendar?month=${month}&class_id=${cid}&section_id=${sid}`); }catch(e){ toast(e.message,false); return; }
  const grid=$('#calGrid'); if(!grid) return;
  grid.innerHTML=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d=>`<div class="muted" style="font-weight:700">${d}</div>`).join('')+data.days.map(d=>{
    const color=d.is_holiday?'#cbd5e1':d.percentage>=90?'var(--green)':d.percentage>=75?'var(--yellow)':'var(--red)';
    return `<div class="cal-day ${d.is_holiday?'holiday':''}" onclick='showCalDetail(${JSON.stringify(d).replace(/'/g,"&#39;")})'><b>${d.date.slice(8)}</b> <small>${d.weekday}</small><br><span class="cal-dot P"></span>${d.present} <span class="cal-dot A"></span>${d.absent} <span class="cal-dot T"></span>${d.late} <span class="cal-dot L"></span>${d.leave}<br><b style="color:${color}">${d.percentage}%</b>${d.is_holiday?'<br><small>Holiday</small>':''}</div>`;
  }).join('');
}
function showCalDetail(d){ const el=$('#calDetail'); if(el) el.innerHTML=`<b>${d.date} (${d.weekday})</b> — Total: ${d.total}, Present: ${d.present}, Absent: ${d.absent}, Late: ${d.late}, Leave: ${d.leave}, Rate: ${d.percentage}%`; }
// ---- ANALYTICS ----
async function loadAnalytics(){
  const cid=$('#anaClass')?.value||'', sid=$('#anaSection')?.value||'';
  let data; try{ data=await api(`/api/analytics?class_id=${cid}&section_id=${sid}`); }catch(e){ toast(e.message,false); return; }
  const w=$('#anaWeekly'); if(w) w.innerHTML=data.weekly.map(x=>`<div style="height:${Math.max(4,x.percentage)}%" title="${x.date} ${x.percentage}%"><span>${x.percentage}%</span></div>`).join('');
  const m=$('#anaMonthly'); if(m) m.innerHTML=data.monthly.map(x=>`<div style="height:${Math.max(4,x.percentage)}%" title="${x.month} ${x.percentage}%"><span>${x.percentage}%</span></div>`).join('');
  const lw=$('#anaLow'); if(lw) lw.innerHTML=data.low_attendance.length? `<table><thead><tr><th>Student</th><th>%</th></tr></thead><tbody>`+data.low_attendance.map(s=>`<tr><td>${s.name} (${s.student_id})</td><td><span class="badge A">${s.percentage}%</span></td></tr>`).join('')+`</tbody></table>` : `<div class="muted">No low attendance 🎉</div>`;
  const hi=$('#anaHigh'); if(hi) hi.innerHTML=data.high_attendance.length? `<table><thead><tr><th>Student</th><th>%</th></tr></thead><tbody>`+data.high_attendance.map(s=>`<tr><td>${s.name} (${s.student_id})</td><td><span class="badge P">${s.percentage}%</span></td></tr>`).join('')+`</tbody></table>` : `<div class="muted">No data</div>`;
  try{
    const logs=await api('/api/audit');
    const at=$('#auditTable');
    if(at) at.innerHTML=logs.length? `<table><thead><tr><th>Date</th><th>Student</th><th>Old → New</th><th>By</th></tr></thead><tbody>`+logs.slice(0,20).map(l=>`<tr><td>${l.date}</td><td>${l.student_name||l.student_id}</td><td>${l.old_status} → ${l.new_status}</td><td>${l.changed_by_name||''}</td></tr>`).join('')+`</tbody></table>` : `<div class="muted">No edits yet</div>`;
  }catch(e){}
}
// ---- NOTIFICATIONS ----
async function loadNotifBadge(){
  try{
    const d=await api('/api/notifications?unread=1');
    const c=$('#notifCount'), dot=$('#bellDot');
    if(c){ if(d.unread>0){ c.textContent=d.unread; c.classList.remove('hidden'); } else c.classList.add('hidden'); }
    if(dot) dot.style.display=d.unread>0?'block':'none';
  }catch(e){}
}
function toggleNotifPanel(e){
  if(e) e.stopPropagation();
  const p=$('#notifPanel'); if(!p) return navigate('notifications');
  p.classList.toggle('hidden');
  if(!p.classList.contains('hidden')) renderNotifPanel();
}
async function renderNotifPanel(){
  const p=$('#notifPanel'); if(!p) return;
  let d; try{ d=await api('/api/notifications'); }catch(e){ p.innerHTML=`<div class="muted">Login required</div>`; return; }
  p.innerHTML=(d.notifications||[]).slice(0,10).map(n=>`<div class="notif-item ${n.read?'':'unread'}"><b>${n.title||n.type}</b><br><small>${n.content||''}</small><br><small class="muted">${n.date||''}</small></div>`).join('')||`<div class="muted">No notifications</div>`;
  p.innerHTML+=`<button class="btn-outline" style="width:100%;margin-top:8px" onclick="navigate('notifications')">View all</button>`;
}
let _notifFilter='all', _notifData=[];
function setNotifFilter(f){
  _notifFilter=f;
  document.querySelectorAll('#notifTabs button').forEach(b=>b.classList.toggle('active', b.dataset.f===f));
  renderNotifPage();
}
async function loadNotifPage(){
  const el=$('#notifList'); if(!el) return;
  el.innerHTML='<div class="sk-wrap"><div class="sk sk-row"></div><div class="sk sk-row"></div><div class="sk sk-row"></div></div>';
  let d; try{ d=await api('/api/notifications'); }catch(e){ el.innerHTML='<div class="card empty"><div class="eic">'+icon('bell')+'</div><h4>Could not load notifications</h4><p>Check your connection and try again.</p></div>'; return; }
  _notifData=(d&&d.notifications)||[];
  renderNotifPage();
}
function renderNotifPage(){
  const el=$('#notifList'); if(!el) return;
  const rows=_notifData.filter(n=>_notifFilter==='all' || !n.read);
  const unread=_notifData.filter(n=>!n.read).length;
  const tabU=document.querySelector('#notifTabs button[data-f="unread"]'); if(tabU) tabU.textContent='Unread ('+unread+')';
  if(!rows.length){
    el.innerHTML='<div class="card empty"><div class="eic">'+icon('bell')+'</div><h4>'+( _notifFilter==='unread'?'All caught up':'No notifications yet')+'</h4><p>Attendance alerts, new notices, e-note uploads and exam reminders will appear here.</p></div>';
    return;
  }
  const kindIcon={alert:'circle-alert',notice:'megaphone',enote:'book-open',exam:'calendar-days',info:'info'};
  const kindTone={alert:'red',notice:'blue',enote:'green',exam:'yellow',info:'blue'};
  el.innerHTML=rows.map(n=>{
    const k=(n.type||'info').toLowerCase();
    return `<div class="list-row ${n.read?'':'unread'}" role="button" tabindex="0"
        onclick="markRead(${n.id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();markRead(${n.id})}">
      <div class="ri ${kindTone[k]||''}">${icon(kindIcon[k]||'bell')}</div>
      <div class="body"><b>${esc(n.title||n.type||'Notification')}</b><p>${esc(n.content||'')}</p>
        <div class="sm muted" style="margin-top:3px">${esc(n.date||'')}</div></div>
      ${n.read?'<span class="chev">'+icon('chevron-right')+'</span>':'<span class="unread-dot" title="Unread"></span>'}
    </div>`;
  }).join('');
}
async function markRead(id){ try{ await api('/api/notifications?id='+id,{method:'DELETE'}); }catch(e){} loadNotifPage(); loadNotifBadge(); }
async function markAllRead(){ try{ await api('/api/notifications?id=all',{method:'DELETE'}); }catch(e){ toast('Could not update notifications',false); return; } loadNotifPage(); loadNotifBadge(); toast('All marked read'); }
async function clearNotifications(){
  if(!confirm('Clear all notifications?')) return;
  try{ await api('/api/notifications?id=all',{method:'DELETE'}); }catch(e){ toast('Could not clear notifications',false); return; }
  _notifData=[]; renderNotifPage(); loadNotifBadge(); toast('Notifications cleared');
}

// ---- SMART COMMAND CENTER ----
async function loadCommandCenter(){
  try{
    const ins=await api('/api/insights');
    const el=$('#ccInsights');
    if(el) el.innerHTML=ins.length? ins.map(i=>`<div class="card" style="border-left:4px solid var(--navy);margin-bottom:8px"><b>${i.icon} ${i.title}</b><p class="muted">${i.text}</p></div>`).join('') : `<div class="muted">No insights yet — mark more attendance.</div>`;
  }catch(e){}
  try{
    const al=await api('/api/alerts');
    const el=$('#ccAlerts');
    if(el) el.innerHTML=al.map(a=>`<div class="card" style="margin-bottom:8px"><b>${a.icon}</b> ${a.text}</div>`).join('');
  }catch(e){}
  try{
    const b=await api('/api/achievements');
    const el=$('#ccBadges');
    if(el) el.innerHTML=b.length? b.map(x=>`<div class="card" style="border-left:4px solid var(--green);margin-bottom:8px"><b>${x.badge}</b><p class="muted">${x.text}</p></div>`).join('') : `<div class="muted">No badges yet.</div>`;
  }catch(e){}
  try{
    const tt=await api('/api/timetable?day='+new Date().toLocaleDateString('en-US',{weekday:'long'}));
    const el=$('#ccTimetable');
    if(el) el.innerHTML=tt.length? `<table><thead><tr><th>Time</th><th>Subject</th><th>Class</th><th></th></tr></thead><tbody>`+tt.slice(0,5).map(t=>`<tr><td>${t.period_time}</td><td>${t.subject_name||''}</td><td>${t.class_name||''}-${t.section_name||''}</td><td>${t.completed?'✓ Completed':`<button class="btn-primary" onclick="quickMark(${t.class_id},${t.section_id},'${t.subject_id||''}')">Mark</button>`}</td></tr>`).join('')+`</tbody></table>` : `<div class="muted">No classes today.</div>`;
  }catch(e){}
  try{
    let sid=state.currentUser?.linked_student_id;
    if(!sid && state.role==='admin'){
      const studs=await api('/api/students');
      sid=studs[0]?.id;
    }
    if(sid){
      const g=await api('/api/goals?student_id='+sid);
      const el=$('#ccGoal');
      if(el) el.innerHTML=`<b>Current: ${g.current}%</b> • Target: ${g.target}%<div class="bar-track" style="margin:8px 0"><div class="bar-fill g" style="width:${Math.min(100,g.current)}%"></div></div><small>${g.remaining}% remaining • ${g.present}/${g.working_days} days</small>`;
    }
  }catch(e){}
}
function quickMark(classId, sectionId, subjectId){
  navigate('attendance');
  setTimeout(()=>{
    if(classId){ const c=$('#attClass'); if(c){ c.value=classId; filterSection('#attSection'); } }
    if(sectionId){ const s=$('#attSection'); if(s) s.value=sectionId; }
    if(subjectId){ const sj=$('#attSubject'); if(sj) sj.value=subjectId; }
    loadAttendance();
  },300);
}
// ---- TIMETABLE ----
// Weekly timetable for every role. The browser only ever renders what the
// server returned: which class a student may see, and which periods a teacher
// is assigned, are decided server-side — never in the query string.
const TT_DAYS=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
const TT_KINDS=['period','break','lunch','assembly'];
const TT_PALETTE=['#2563eb','#0891b2','#16a34a','#d97706','#db2777','#7c3aed','#0d9488','#dc2626','#4f46e5','#65a30d'];
const TT_ZONES=['Asia/Kolkata','Asia/Dhaka','Asia/Karachi','Asia/Colombo','Asia/Kathmandu','Asia/Dubai',
  'Europe/London','Europe/Berlin','America/New_York','America/Chicago','America/Los_Angeles',
  'Australia/Sydney','Africa/Nairobi','Africa/Lagos'];
const ttState={payload:null,tab:'grid',versions:[],version:null,versionId:null,rows:[],
  subjects:[],teachers:[],sessions:[],metaLoaded:false};

function ttIsStudent(){ return state.role==='student'||state.role==='parent'; }
function ttIsAdmin(){ return state.role==='admin'; }
/* Deterministic per-subject colour so the same subject is always the same hue,
   with no configuration to maintain. */
function ttColor(name){
  if(!name) return '#94a3b8';
  const s=String(name); let h=0;
  for(let i=0;i<s.length;i++) h=(h*31+s.charCodeAt(i))>>>0;
  return TT_PALETTE[h%TT_PALETTE.length];
}
function ttMin(hhmm){
  const m=/^(\d{1,2}):(\d{2})$/.exec(String(hhmm||'').trim());
  if(!m) return null;
  const h=+m[1],mi=+m[2];
  return (h>23||mi>59)?null:h*60+mi;
}
function ttAddMin(hhmm,n){
  const m=ttMin(hhmm); if(m==null) return hhmm||'08:00';
  const t=Math.min(23*60+59,m+n);
  return String(Math.floor(t/60)).padStart(2,'0')+':'+String(t%60).padStart(2,'0');
}
/* Date maths kept in local time: toISOString() would shift days either side of
   midnight UTC and quietly show the wrong weekday column. */
function ttAddDays(iso,n){
  const [y,m,d]=iso.split('-').map(Number);
  const dt=new Date(y,m-1,d+n);
  return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;
}
function ttWeekStart(iso){
  const [y,m,d]=iso.split('-').map(Number);
  return ttAddDays(iso,-((new Date(y,m-1,d).getDay()+6)%7));
}
function ttEmpty(ic,title,text,extra){
  return `<div class="empty"><div class="eic"><span class="ic" data-icon="${ic}"></span></div>`+
    `<h4>${esc(title)}</h4><p>${esc(text)}</p>${extra||''}</div>`;
}
function ttOpts(opts,val){
  return opts.map(o=>`<option value="${escAttr(o.v)}"${String(o.v)===String(val??'')?' selected':''}>${esc(o.t)}</option>`).join('');
}
function ttQuery(extra){
  const q=new URLSearchParams();
  const cid=$('#ttClass')?.value, sid=$('#ttSection')?.value,
        ses=$('#ttSession')?.value, dt=$('#ttDate')?.value;
  if(cid) q.set('class_id',cid);
  if(sid) q.set('section_id',sid);
  if(ses) q.set('session_id',ses);
  if(dt) q.set('date',dt);
  if(state.role==='teacher' && !cid) q.set('view','mine');
  if(extra) Object.entries(extra).forEach(([k,v])=>{ if(v!==''&&v!=null) q.set(k,v); });
  return q.toString();
}

async function loadTimetable(){
  const grid=$('#ttGrid'); if(!grid) return;
  const student=ttIsStudent(), admin=ttIsAdmin(), teacher=state.role==='teacher';
  // Class/section are meaningless for students and parents — the server derives
  // them from the account link, so hide the controls rather than let them lie.
  ['ttClass','ttSection','ttSession'].forEach(id=>$('#'+id)?.classList.toggle('hidden',student));
  $('#ttTabEdit')?.classList.toggle('hidden',!admin);
  $('#ttTabSettings')?.classList.toggle('hidden',!admin);
  $('#ttTabHistory')?.classList.toggle('hidden',!admin);
  const head=$('#ttHeadActions');
  if(head) head.innerHTML=
    `<button class="btn-outline" onclick="ttPrint()"><span class="ic" data-icon="file-text"></span> Print</button>`+
    `<button class="btn-outline" onclick="ttPdf()"><span class="ic" data-icon="file-down"></span> PDF</button>`;
  if(!$('#ttDate').value) $('#ttDate').value=new Date().toISOString().slice(0,10);
  if(!ttState.sessions.length){
    try{ ttState.sessions=await api('/api/sessions'); }catch(e){ ttState.sessions=[]; }
    const sel=$('#ttSession');
    if(sel) sel.innerHTML=ttState.sessions.map(s=>`<option value="${s.id}">${esc(s.name)}${s.active?' • active':''}</option>`).join('');
  }
  // Admins get a concrete class so the grid is never blank on first open;
  // teachers default to "My periods" (no class selected) instead.
  if(admin && !$('#ttClass').value && (state.classes||[]).length){
    $('#ttClass').value=state.classes[0].id;
    filterSection('#ttSection');
    const s=$('#ttSection'); if(s&&s.options.length>1) s.value=s.options[1].value;
  }
  grid.innerHTML='<div class="sk-wrap">'+Array(6).fill('<div class="sk sk-row"></div>').join('')+'</div>';
  $('#ttToday').innerHTML=''; $('#ttLegend').innerHTML='';
  let p;
  try{ p=await api('/api/timetable/schedule?'+ttQuery()); }
  catch(e){
    grid.innerHTML=ttEmpty('triangle-alert','Could not load the timetable',e.message||'Please try again.');
    paintIcons(document); return;
  }
  ttState.payload=p;
  const mine = teacher && !$('#ttClass').value;
  const t=$('#ttTitle'), s=$('#ttSub');
  if(t) t.textContent = mine ? 'My Timetable'
    : (p.scope?.class_name ? `Class ${p.scope.class_name}-${p.scope.section_name}` : 'Timetable');
  if(s) s.textContent = p.published
    ? `Effective from ${esc(p.version?.effective_from||'')}${p.version?.name?' • '+esc(p.version.name):''}`
    : 'No timetable has been published for this class yet.';
  ttStrip(p); ttLegend(p); ttGrid(p);
  paintIcons(document);
}

function ttStrip(p){
  const el=$('#ttToday'); if(!el) return;
  if(p.link_required){
    el.innerHTML=ttEmpty('user-check','Staff account not linked',
      p.message||'Ask an administrator to link your account to a teaching record.');
    return;
  }
  const bits=[];
  const hol=(p.holidays||[]).find(h=>h.date===p.date);
  if(hol) bits.push(`<div class="st holiday"><span class="ic" data-icon="calendar"></span>`+
    `<span><b>${esc(hol.name)}</b> — no classes today</span></div>`);
  if(p.current_slot){
    const c=p.current_slot;
    bits.push(`<div class="st live"><span class="ic" data-icon="clock"></span>`+
      `<span>Now: <b>${esc(c.subject_name||c.name||'')}</b> ${esc(c.start_time)}–${esc(c.end_time)}</span></div>`);
  }else if(p.next_slot){
    const c=p.next_slot;
    bits.push(`<div class="st"><span class="ic" data-icon="clock"></span>`+
      `<span>Next: <b>${esc(c.subject_name||c.name||'')}</b> at ${esc(c.start_time)}</span></div>`);
  }else if(p.published){
    bits.push(`<div class="st"><span class="ic" data-icon="clock"></span>`+
      `<span>No more periods on ${esc(p.weekday||'this day')}</span></div>`);
  }
  (p.substitutions||[]).forEach(s=>{
    bits.push(`<div class="st"><span class="ic" data-icon="refresh-cw"></span><span>`+
      `<b>${esc(s.substitute_name||'')}</b> covers ${esc(s.original_name||'')}'s `+
      `${esc(s.slot_name||'period')} • ${esc(s.start_time)}–${esc(s.end_time)}</span></div>`);
  });
  el.innerHTML = bits.length ? `<div class="tt-strip">${bits.join('')}</div>`
    : `<div class="muted" style="font-size:13.5px">${p.published?'No schedule highlights for today.':'Nothing scheduled yet.'}</div>`;
}

function ttLegend(p){
  const el=$('#ttLegend'); if(!el) return;
  const names=new Set();
  (p.days||[]).forEach(d=>(d.slots||[]).forEach(s=>{ if(s.subject_name) names.add(s.subject_name); }));
  if(!names.size){ el.innerHTML=''; el.classList.add('hidden'); return; }
  el.classList.remove('hidden');
  el.innerHTML=`<div class="tt-legend">`+
    [...names].sort().map(n=>`<span><i class="tt-swatch" style="background:${ttColor(n)}"></i>${esc(n)}</span>`).join('')+
    `<span><i class="tt-swatch" style="background:#fffbeb;box-shadow:inset 0 0 0 1px #f59e0b"></i> Break / Lunch</span>`+
    `</div>`;
}

function ttGrid(p){
  const grid=$('#ttGrid'); if(!grid) return;
  const days=p.days||[];
  const starts=new Set();
  days.forEach(d=>(d.slots||[]).forEach(s=>starts.add(s.start_time)));
  const times=[...starts].sort();
  if(!times.length){
    grid.innerHTML=ttEmpty('calendar','No timetable published yet',
      ttIsAdmin()?'Open the Edit tab to build a week, then publish it.'
                 :'Your school has not published a timetable for this class yet.');
    return;
  }
  // Rows are time bands: each starts at its own time and ends where the next one begins.
  const bands=times.map((t,i)=>({start:t,end:i+1<times.length?times[i+1]:null}));
  const lastEnd=days.flatMap(d=>(d.slots||[]).map(s=>s.end_time)).filter(Boolean).sort().slice(-1)[0];
  const ws=ttWeekStart(p.date);
  const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const colDates=days.map((d,i)=>ttAddDays(ws,i));
  let html=`<div class="tt-grid" style="grid-template-columns:96px repeat(${days.length},minmax(150px,1fr))">`;
  html+=`<div class="tt-h tt-time">Time</div>`;
  days.forEach((d,i)=>{
    const cd=colDates[i], dt=new Date(cd+'T00:00:00');
    const isSel=(cd===p.date);
    html+=`<div class="tt-h">${esc(d.day)}<small>${dt.getDate()} ${MON[dt.getMonth()]}${isSel?' • shown':''}</small></div>`;
  });
  times.forEach(t=>{
    const b=bands.find(x=>x.start===t);
    const bandEnd=b.end||(lastEnd&&lastEnd>t?lastEnd:null);
    html+=`<div class="tt-time">${esc(t)}${bandEnd?'<br>'+esc(bandEnd):''}</div>`;
    days.forEach((d,i)=>{
      const s=(d.slots||[]).find(x=>x.start_time===t);
      html+=ttCell(s,p,d.day,colDates[i]);
    });
  });
  html+='</div>';
  grid.innerHTML=html;
}

function ttCell(s,p,day,colDate){
  if(!s) return `<div class="tt-cell is-empty" title="Free period"></div>`;
  const cls=['tt-cell'];
  if(s.kind&&s.kind!=='period') cls.push('is-break');
  if(s.status==='cancelled') cls.push('is-cancelled');
  const isNow=!!(p.current_slot && p.current_slot.day===day && p.current_slot.start_time===s.start_time);
  if(isNow) cls.push('is-now');
  if(s.substitute_name) cls.push('is-sub');
  const label=s.subject_name||s.name||'';
  const sw=(s.kind==='period')?`<i class="tt-swatch" style="background:${ttColor(label)}"></i>`:'';
  const meta=[];
  if(p.scope?.view==='mine'&&s.class_name) meta.push(`<span>Class ${esc(s.class_name)}-${esc(s.section_name||'')}</span>`);
  if(s.substitute_name) meta.push(`<span><b>${esc(s.substitute_name)}</b> replacing ${esc(s.teacher_name||'')}</span>`);
  else if(s.teacher_name) meta.push(`<span>${esc(s.teacher_name)}</span>`);
  if(s.room) meta.push(`<span><span class="ic" data-icon="map-pin"></span>${esc(s.room)}</span>`);
  if(isNow) meta.push(`<span class="tt-tag now">Now</span>`);
  if(s.substitute_name) meta.push(`<span class="tt-tag sub">Substitute</span>`);
  if(s.status==='cancelled') meta.push(`<span class="tt-tag off">Cancelled</span>`);
  return `<div class="${cls.join(' ')}" title="${escAttr(label+' '+s.start_time+'–'+s.end_time)}">`+
    `<div class="tt-sub">${sw}<span>${esc(label)}</span></div>`+
    (meta.length?`<div class="tt-meta">${meta.join('')}</div>`:'')+
    `<div class="tt-meta muted">${esc(s.start_time)}–${esc(s.end_time)}</div></div>`;
}

function ttClassChanged(){ filterSection('#ttSection'); loadTimetable(); }
function ttPrint(){ window.print(); }
function ttPdf(){ window.open('/api/timetable/pdf?'+ttQuery(),'_blank','noopener'); }

function ttTab(name){
  ttState.tab=name;
  document.querySelectorAll('#ttTabs button').forEach(b=>b.classList.toggle('active',b.dataset.ttTab===name));
  ['grid','edit','settings','history'].forEach(n=>$('#ttp-'+n)?.classList.toggle('hidden',n!==name));
  if(name==='edit') ttLoadRefData().then(ttLoadVersions);
  if(name==='settings') ttLoadSettings();
  if(name==='history') ttLoadHistory();
}
async function ttLoadRefData(){
  if(ttState.metaLoaded) return;
  try{
    const [s,t]=await Promise.all([api('/api/subjects'), api('/api/teachers')]);
    ttState.subjects=Array.isArray(s)?s:(s.subjects||[]);
    ttState.teachers=Array.isArray(t)?t:(t.teachers||[]);
    ttState.metaLoaded=true;
  }catch(e){ /* leave the lists empty; the selects still render */ }
}
async function ttLoadVersions(){
  const sel=$('#ttvSelect');
  const cid=$('#ttClass')?.value, sid=$('#ttSection')?.value;
  if(!cid||!sid){
    if(sel) sel.innerHTML='<option value="">Choose a class and section first</option>';
    ttState.version=null; ttState.rows=[]; ttMeta(); ttRows(); return;
  }
  let list=[];
  try{ list=await api(`/api/timetable/versions?class_id=${cid}&section_id=${sid}`); }catch(e){
    if(sel) sel.innerHTML='<option value="">Could not load timetables</option>';
    return;
  }
  ttState.versions=list;
  if(!list.length){
    if(sel) sel.innerHTML='<option value="">No timetables yet — create a draft</option>';
    ttState.version=null; ttState.versionId=null; ttState.rows=[]; ttMeta(); ttRows(); return;
  }
  const keep=list.find(v=>v.id===ttState.versionId)||list[0];
  if(sel) sel.innerHTML=list.map(v=>
    `<option value="${v.id}"${v.id===keep.id?' selected':''}>#${v.id} • ${esc(v.name||'Untitled')} • ${esc(v.status)} • eff ${esc(v.effective_from)} • ${v.slot_count} cells</option>`).join('');
  await ttLoadVersion();
}
async function ttLoadVersion(){
  const vid=$('#ttvSelect')?.value;
  if(!vid){ ttState.version=null; ttState.rows=[]; ttMeta(); ttRows(); return; }
  let d;
  try{ d=await api('/api/timetable/versions/'+vid); }
  catch(e){ toast(e.message,false); return; }
  ttState.version=d.version; ttState.versionId=+vid;
  ttState.rows=(d.slots||[]).map(s=>({
    day:s.day,start_time:s.start_time,end_time:s.end_time,name:s.name||'',kind:s.kind||'period',
    subject_id:s.subject_id,teacher_id:s.teacher_id,substitute_teacher_id:s.substitute_teacher_id||null,
    room:s.room||'',status:s.status||'active',cancel_reason:s.cancel_reason||'',notes:s.notes||''
  }));
  ttMeta(); ttRows(); ttErrorsShow(null,null);
}
function ttMeta(){
  const v=ttState.version, el=$('#ttEditMeta'); if(!el) return;
  if(!v){ el.innerHTML='<div class="muted">Select or create a draft to start editing.</div>'; return; }
  const pub=v.status==='published';
  const pubBtn=$('#ttPublishBtn'); if(pubBtn) pubBtn.classList.toggle('hidden',pub);
  el.innerHTML=`<div class="tt-form"><div class="tt-fgrid">
      <div class="tt-field"><label>Name</label>
        <input id="ttvName" value="${escAttr(v.name||'')}" placeholder="e.g. Term 1" ${pub?'disabled':''}></div>
      <div class="tt-field"><label>Effective from</label>
        <input id="ttvEff" type="date" value="${escAttr(v.effective_from||'')}" ${pub?'disabled':''}></div>
      <div class="tt-field"><label>Status</label><input value="${esc(v.status)}" disabled></div>
    </div>
    ${pub?`<p class="muted" style="font-size:13px;margin:0">Published timetables are locked so the
      change history stays accurate. Use <b>Duplicate</b> to make an editable draft.</p>`:''}
  </div>`;
}
function ttRows(){
  const wrap=$('#ttRows'); if(!wrap) return;
  const v=ttState.version;
  const locked=!v||v.status==='published';
  if(!ttState.rows.length){
    wrap.innerHTML=`<div class="muted" style="padding:14px 0">No periods yet — use <b>Add period</b> to build the week.</div>`;
    return;
  }
  const subs=[{v:'',t:'—'}].concat(ttState.subjects.map(s=>({v:s.id,t:s.name})));
  const teas=[{v:'',t:'—'}].concat(ttState.teachers.map(t=>({v:t.id,t:t.name})));
  const days=TT_DAYS.map(d=>({v:d,t:d.slice(0,3)}));
  const kinds=TT_KINDS.map(k=>({v:k,t:k[0].toUpperCase()+k.slice(1)}));
  const sts=[{v:'active',t:'Active'},{v:'cancelled',t:'Cancelled'}];
  wrap.innerHTML=`<div class="tt-rowhead"><span>Day</span><span>Start</span><span>End</span>`+
    `<span>Subject</span><span>Teacher</span><span>Room</span><span>Type</span><span>Status</span><span></span></div>`+
    `<div class="tt-rows">${ttState.rows.map((r,i)=>{
      const dis=locked?' disabled':'';
      return `<div class="tt-row">
        <select onchange="ttField(${i},'day',this.value)"${dis}>${ttOpts(days,r.day)}</select>
        <input type="time" value="${escAttr(r.start_time)}" onchange="ttField(${i},'start_time',this.value)"${dis}>
        <input type="time" value="${escAttr(r.end_time)}" onchange="ttField(${i},'end_time',this.value)"${dis}>
        <select onchange="ttField(${i},'subject_id',this.value)"${dis}>${ttOpts(subs,r.subject_id)}</select>
        <select onchange="ttField(${i},'teacher_id',this.value)"${dis}>${ttOpts(teas,r.teacher_id)}</select>
        <input value="${escAttr(r.room||'')}" placeholder="Room" onchange="ttField(${i},'room',this.value)"${dis}>
        <select onchange="ttField(${i},'kind',this.value)"${dis}>${ttOpts(kinds,r.kind)}</select>
        <select onchange="ttField(${i},'status',this.value)"${dis}>${ttOpts(sts,r.status||'active')}</select>
        <button class="tt-kill" onclick="ttDelRow(${i})" title="Remove period"${dis}>`+
          `<span class="ic" data-icon="trash-2"></span></button>
      </div>`;
    }).join('')}</div>`;
  paintIcons(wrap);
}
function ttField(i,k,v){
  const r=ttState.rows[i]; if(!r) return;
  if(k==='subject_id'||k==='teacher_id') r[k]=v?+v:null;
  else r[k]=v;
  if(k==='kind'){
    r.name = v==='period' ? (ttState.subjects.find(s=>s.id===r.subject_id)?.name||'')
                          : v[0].toUpperCase()+v.slice(1);
    if(v!=='period'){ r.subject_id=null; r.teacher_id=null; ttRows(); }
  }
  if(k==='subject_id'&&v){
    const s=ttState.subjects.find(x=>x.id===+v);
    if(s) r.name=s.name;
  }
}
function ttAddRow(){
  const v=ttState.version;
  if(!v) return toast('Create or select a draft first',false);
  if(v.status==='published') return toast('Published timetables are locked — duplicate to edit',false);
  const monday=ttState.rows.filter(r=>r.day==='Monday').sort((a,b)=>a.start_time.localeCompare(b.start_time));
  const last=monday[monday.length-1];
  const st=last?ttAddMin(last.end_time,15):'08:00';
  ttState.rows.push({day:'Monday',start_time:st,end_time:ttAddMin(st,45),name:'',kind:'period',
    subject_id:null,teacher_id:null,substitute_teacher_id:null,room:'',status:'active',
    cancel_reason:'',notes:''});
  ttRows();
}
function ttDelRow(i){
  if(!ttState.rows[i]) return;
  ttState.rows.splice(i,1);
  ttRows();
}
function ttErrorsShow(errs,warns){
  const el=$('#ttErrors'); if(!el) return;
  const E=errs||[], W=warns||[];
  if(!E.length && !W.length){ el.classList.add('hidden'); el.innerHTML=''; return; }
  el.classList.remove('hidden');
  el.innerHTML=`<h4><span class="ic" data-icon="triangle-alert"></span> `+
    (E.length?`${E.length} conflict${E.length>1?'s':''} to fix`:'Saved with warnings')+`</h4><ul>`+
    E.map(e=>`<li><span class="ic" data-icon="circle-alert"></span><span>${esc(e.message)}</span></li>`).join('')+
    W.map(w=>`<li class="ok"><span class="ic" data-icon="info"></span><span>${esc(w.message)}</span></li>`).join('')+
    `</ul>`;
  paintIcons(el);
}
function ttPayload(){
  return ttState.rows.map(r=>({
    day:r.day,start_time:r.start_time,end_time:r.end_time,name:r.name||'',
    kind:r.kind||'period',subject_id:r.subject_id,teacher_id:r.teacher_id,
    substitute_teacher_id:r.substitute_teacher_id||null,room:r.room||'',
    status:r.status||'active',cancel_reason:r.cancel_reason||'',notes:r.notes||''
  }));
}
async function ttValidate(){
  const v=ttState.version;
  if(!v) return toast('Select a draft first',false);
  let r;
  try{ r=await api('/api/timetable/validate',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({version_id:v.id,slots:ttPayload()})}); }
  catch(e){ return toast(e.message,false); }
  ttErrorsShow(r.errors||[],r.warnings||[]);
  toast(r.ok?'No conflicts found':`${(r.errors||[]).length} conflict(s) found`, !!r.ok);
}
async function ttSave(){
  const v=ttState.version;
  if(!v) return toast('Select a draft first',false);
  if(v.status==='published') return toast('Published timetables are locked — duplicate to edit',false);
  const put=(body)=>api('/api/timetable/versions/'+v.id,{method:'PUT',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const name=$('#ttvName')?.value, eff=$('#ttvEff')?.value;
  if(name!==undefined && name!==(v.name||'')){ try{ await put({name}); }catch(e){ return toast(e.message,false); } }
  if(eff && eff!==v.effective_from){ try{ await put({effective_from:eff}); }catch(e){ return toast(e.message,false); } }
  let res;
  try{
    res=await api('/api/timetable/versions/'+v.id+'/slots',{method:'PUT',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({slots:ttPayload()})});
  }catch(e){
    const b=e.body||{};
    ttErrorsShow(b.errors||[{code:'error',message:e.message}],b.warnings||[]);
    return toast(e.message||'Save blocked',false);
  }
  ttErrorsShow([],res.warnings||[]);
  toast('Timetable saved');
  await ttLoadVersions();
  loadTimetable();
}
async function ttNewVersion(){
  const cid=$('#ttClass')?.value, sid=$('#ttSection')?.value;
  if(!cid||!sid) return toast('Choose a class and section first',false);
  try{
    const r=await api('/api/timetable/versions',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({class_id:+cid,section_id:+sid,name:'New timetable',
        effective_from:new Date().toISOString().slice(0,10)})});
    ttState.versionId=r.id;
    toast('Draft created');
    await ttLoadVersions();
    $('#ttvName')?.focus();
  }catch(e){ toast(e.message,false); }
}
async function ttPublish(){
  const v=ttState.version;
  if(!v) return toast('Select a draft first',false);
  if(v.status==='published') return toast('Already published',false);
  if(!ttState.rows.length) return toast('Add at least one period first',false);
  const eff=$('#ttvEff')?.value||v.effective_from;
  if(!confirm(`Publish this timetable from ${eff}? Students, parents and teachers will be notified in-app.`)) return;
  try{
    const r=await api('/api/timetable/versions/'+v.id+'/publish',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({effective_from:eff})});
    const n=r.notifications||{};
    ttErrorsShow([],r.warnings||[]);
    toast(`Published • ${n.created||0} in-app notification${(n.created||0)===1?'':'s'}`);
    await ttLoadVersions();
    loadTimetable();
  }catch(e){
    const b=e.body||{};
    ttErrorsShow(b.errors||[{code:'error',message:e.message}],[]);
    toast(e.message||'Publish failed',false);
  }
}
async function ttArchive(){
  const v=ttState.version;
  if(!v) return toast('Select a draft first',false);
  if(v.status==='archived') return toast('Already archived',false);
  // Archiving is how a published timetable is retired without erasing the
  // record of what was actually in force.
  if(!confirm('Archive this timetable? It stops being shown to students and teachers, but stays in the history.')) return;
  try{
    await api('/api/timetable/versions/'+v.id+'/archive',{method:'POST'});
    toast('Archived'); await ttLoadVersions(); loadTimetable();
  }catch(e){ toast(e.message,false); }
}
async function ttDeleteVersion(){
  const v=ttState.version;
  if(!v) return toast('Select a draft first',false);
  if(v.status==='published') return toast('Published timetables cannot be deleted — archive instead',false);
  if(!confirm('Delete this draft timetable?')) return;
  try{
    await api('/api/timetable/versions/'+v.id,{method:'DELETE'});
    ttState.versionId=null; toast('Deleted'); await ttLoadVersions(); loadTimetable();
  }catch(e){ toast(e.message,false); }
}
async function ttDuplicateOpen(){
  const el=$('#ttDup'); if(!el) return;
  const v=ttState.version;
  if(!v) return toast('Select a timetable first',false);
  if(el.classList.contains('hidden')){
    const drafts=ttState.versions.filter(x=>x.status!=='published'&&x.id!==v.id);
    const cls=(state.classes||[]);
    el.classList.remove('hidden');
    el.innerHTML=`<div class="card-head"><h3><span class="ic" data-icon="files"></span> Duplicate</h3>
      <button class="btn-outline" onclick="$('#ttDup').classList.add('hidden')">Close</button></div>
      <div class="tt-form">
        <div><b style="font-size:13px">Copy one day to other days</b>
          <div class="toolbar" style="margin-top:7px">
            <select id="dupFrom">${ttOpts(TT_DAYS.map(d=>({v:d,t:d})),v.status==='published'?'Monday':'')}</select>
            ${TT_DAYS.map(d=>`<label style="font-size:12.5px"><input type="checkbox" value="${d}" class="dupTo"> ${d.slice(0,3)}</label>`).join('')}
            <button class="btn-outline" onclick="ttDupDay()">Copy day</button>
          </div></div>
        <div><b style="font-size:13px">Copy this week into another draft</b>
          <div class="toolbar" style="margin-top:7px">
            <select id="dupWeek">${drafts.length?ttOpts(drafts.map(x=>({v:x.id,t:`#${x.id} ${x.name||'Untitled'} (${x.status})`})),drafts[0]?.id):'<option value="">No other drafts</option>'}</select>
            <button class="btn-outline" onclick="ttDupWeek()">Copy week</button>
          </div></div>
        <div><b style="font-size:13px">Copy this week into another class</b>
          <p class="muted" style="font-size:12.5px;margin:4px 0 7px">The day structure is copied; teachers
            and rooms are cleared so you can assign the right staff (a teacher can only cover one class at a time).</p>
          <div class="toolbar">
            <select id="dupClass">${ttOpts(cls.map(c=>({v:c.id,t:'Class '+c.name})),cls[0]?.id)}</select>
            <select id="dupSection"></select>
            <input type="date" id="dupEff" value="${new Date().toISOString().slice(0,10)}">
            <button class="btn-outline" onclick="ttDupClass()">Copy to class</button>
          </div></div>
      </div>`;
    const cs=$('#dupClass');
    if(cs){
      const fill=()=>{ const c=cls.find(x=>x.id==cs.value); $('#dupSection').innerHTML=ttOpts((c?.sections||[]).map(s=>({v:s.id,t:s.name})),c?.sections?.[0]?.id); };
      cs.onchange=fill; fill();
    }
    paintIcons(el);
    return;
  }
  el.classList.add('hidden');
}
function ttDupDay(){
  const v=ttState.version;
  const from=$('#dupFrom')?.value;
  const to=[...document.querySelectorAll('.dupTo:checked')].map(x=>x.value);
  if(!v||!from||!to.length) return toast('Pick a source day and at least one target',false);
  api(`/api/timetable/versions/${v.id}/duplicate`,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'day',from_day:from,to_days:to})})
    .then(r=>{ toast(`Copied ${from} to ${to.join(', ')}`); ttLoadVersions(); loadTimetable(); })
    .catch(e=>{ const b=e.body||{}; ttErrorsShow(b.errors||[{code:'error',message:e.message}],[]);
      toast(e.message||'Copy blocked',false); });
}
function ttDupWeek(){
  const v=ttState.version, to=$('#dupWeek')?.value;
  if(!v||!to) return toast('Pick a destination draft',false);
  api(`/api/timetable/versions/${v.id}/duplicate`,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'week',to_version_id:+to})})
    .then(r=>{ toast(`Copied ${r.copied} cells`); ttState.versionId=+to; ttLoadVersions(); loadTimetable(); })
    .catch(e=>{ const b=e.body||{}; ttErrorsShow(b.errors||[{code:'error',message:e.message}],[]);
      toast(e.message||'Copy blocked',false); });
}
function ttDupClass(){
  const v=ttState.version;
  const cid=$('#dupClass')?.value, sid=$('#dupSection')?.value, eff=$('#dupEff')?.value;
  if(!v||!cid||!sid) return toast('Pick a target class and section',false);
  api(`/api/timetable/versions/${v.id}/duplicate`,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:'class',to_class_id:+cid,to_section_id:+sid,effective_from:eff})})
    .then(r=>{
      const cleared=r.cleared_teachers||0;
      toast(`Copied ${r.copied} cells${cleared?` • ${cleared} need a teacher`:''}`);
      $('#ttClass').value=cid; filterSection('#ttSection'); $('#ttSection').value=sid;
      ttState.versionId=r.id;
      $('#ttDup').classList.add('hidden');
      ttLoadVersions(); loadTimetable();
    })
    .catch(e=>{ const b=e.body||{}; ttErrorsShow(b.errors||[{code:'error',message:e.message}],[]);
      toast(e.message||'Copy blocked',false); });
}
async function ttLoadSettings(){
  const el=$('#ttSettingsForm'); if(!el) return;
  let s;
  try{ s=await api('/api/timetable/settings?'+ttQuery()); }catch(e){ return toast(e.message,false); }
  const zones=[...new Set([s.timezone,...TT_ZONES])];
  const work=new Set(s.working_days||TT_DAYS);
  el.innerHTML=`<div class="card-head"><h3><span class="ic" data-icon="settings"></span> School day</h3></div>
    <div class="tt-form">
      <div class="tt-fgrid">
        <div class="tt-field"><label>Opens</label><input type="time" id="setOpen" value="${escAttr(s.open_time)}"></div>
        <div class="tt-field"><label>Closes</label><input type="time" id="setClose" value="${escAttr(s.close_time)}"></div>
        <div class="tt-field"><label>Default period length (minutes)</label>
          <input type="number" id="setPeriod" min="5" max="240" value="${escAttr(s.period_minutes)}"></div>
        <div class="tt-field"><label>Timezone</label>
          <select id="setTz">${ttOpts(zones.map(z=>({v:z,t:z})),s.timezone)}</select></div>
      </div>
      <div class="tt-field"><label>Working days</label>
        <div class="tt-chips">${TT_DAYS.map(d=>`<label><input type="checkbox" class="setDay" value="${d}"${
          work.has(d)?' checked':''}> ${d}</label>`).join('')}</div></div>
      <p class="muted" style="font-size:12.5px;margin:0">Applies to ${
        s.scope==='class'?`Class ${s.class_name||''} only`
        :s.scope==='global'?'every class (school-wide default)'
        :'all classes (built-in defaults — nothing saved yet)'}. Periods outside these
        hours are rejected by the server.</p>
      <div class="toolbar"><button class="btn-primary" onclick="ttSaveSettings()">`+
        `<span class="ic" data-icon="circle-check"></span> Save settings</button></div>
    </div>`;
  paintIcons(el);
}
async function ttSaveSettings(){
  const days=[...document.querySelectorAll('.setDay:checked')].map(x=>x.value);
  if(!days.length) return toast('Pick at least one working day',false);
  const q=ttQuery();
  try{
    await api('/api/timetable/settings'+(q?'?'+q:''),{method:'PUT',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({open_time:$('#setOpen').value,close_time:$('#setClose').value,
        timezone:$('#setTz').value,working_days:days,period_minutes:+$('#setPeriod').value})});
    toast('Settings saved'); loadTimetable();
  }catch(e){ toast(e.message,false); }
}
async function ttLoadHistory(){
  const el=$('#ttHistory'); if(!el) return;
  const q=ttQuery();
  let rows;
  try{ rows=await api('/api/timetable/history'+(q?'?'+q:'')); }
  catch(e){ return toast(e.message,false); }
  if(!rows.length){
    el.innerHTML=ttEmpty('scroll-text','No changes yet','Publishing, editing and duplicating a timetable all get recorded here.');
    paintIcons(el); return;
  }
  const ICONS={publish:'upload',create:'plus',edit:'pencil',delete:'trash-2',
    duplicate:'files',archive:'folder-open',substitute:'refresh-cw',settings:'settings',migrate:'refresh-cw'};
  el.innerHTML=`<div class="card-head"><h3><span class="ic" data-icon="scroll-text"></span> Change history</h3></div>
    <div class="tt-hist">${rows.map(h=>{
      const det=h.detail||{};
      const extra=[det.effective_from?`eff ${esc(det.effective_from)}`:'',
        det.slots?`${det.slots} cells`:'',det.cells?`${det.cells} cells`:'',
        det.cleared_teachers?`${det.cleared_teachers} staff cleared`:'',
        det.note?esc(det.note):''].filter(Boolean).join(' • ');
      return `<div class="h"><span class="ic" data-icon="${ICONS[h.action]||'info'}"></span><div class="hb">
        <b>${esc(h.summary||h.action)}</b>
        ${h.class_name?`<p>Class ${esc(h.class_name)}-${esc(h.section_name||'')}</p>`:''}
        ${extra?`<p>${extra}</p>`:''}
        <time>${esc(h.changed_by_name||'system')} • ${esc((h.changed_at||'').slice(0,16).replace('T',' '))}</time>
      </div></div>`;
    }).join('')}</div>`;
  paintIcons(el);
}

// ---- HEATMAP ----
function initHeatmap(){ const el=$('#heatMonth'); if(el && !el.value) el.value=new Date().toISOString().slice(0,7); loadHeatmap(); }
async function loadHeatmap(){
  const month=$('#heatMonth').value; if(!month) return toast('Select month',false);
  let data; try{ data=await api('/api/heatmap?month='+month); }catch(e){ return; }
  const el=$('#heatGrid'); if(!el) return;
  const days=data.grid[0]?.days.map(d=>d.date.slice(8))||[];
  el.innerHTML=`<table><thead><tr><th>Class</th>`+days.map(d=>`<th>${d}</th>`).join('')+`</tr></thead><tbody>`+data.grid.map(r=>`<tr><td><b>${r.class}</b></td>`+r.days.map(d=>{
    const bg=d.level==='high'?'#dcfce7':d.level==='medium'?'#fef3c7':d.level==='low'?'#fee2e2':'#f1f5f9';
    const dot=d.level==='high'?'<i class="cal-dot P"></i>':d.level==='medium'?'<i class="cal-dot L"></i>':d.level==='low'?'<i class="cal-dot A"></i>':'<span class="muted">—</span>';
    return `<td style="background:${bg};text-align:center" title="${d.date} ${d.percentage}%">${dot}<br><small>${d.percentage>=0?d.percentage+'%':''}</small></td>`;
  }).join('')+`</tr>`).join('')+`</tbody></table>`;
}
// ---- DIGITAL ID ----
async function initIdCard(){
  try{
    const studs=await api('/api/students');
    const sel=$('#idStudent'); if(sel) sel.innerHTML=studs.map(s=>`<option value="${s.id}">${s.name} (${s.student_id})</option>`).join('');
  }catch(e){}
}
async function loadIdCard(){
  const sid=$('#idStudent')?.value;
  if(!sid) return toast('Select student',false);
  let d; try{ d=await api('/api/student_id_card?student_id='+sid); }catch(e){ toast(e.message,false); return; }
  const el=$('#idCard');
  if(el) el.innerHTML=`<div style="border:2px solid var(--navy);border-radius:14px;padding:16px"><div style="font-weight:700">🏫 ${d.school}</div><img src="${d.photo?BACKEND_URL+'/api/photos/'+d.photo:'https://ui-avatars.com/api/?name='+encodeURIComponent(d.name)+'&background=1E3A8A&color=fff'}" style="width:80px;height:80px;border-radius:50%;margin:8px"><div><b>${d.name}</b></div><small>ID: ${d.student_id} • Class ${d.class}-${d.section} • Roll ${d.roll||''}</small><br><img src="${BACKEND_URL}${d.qr_url}" style="width:140px;height:140px;margin-top:8px;border:1px solid #e2e8f0;border-radius:8px"><br><small class="muted">QR contains ID only — no personal data</small></div>`;
}
// ---- TIMELINE + REVIEWS ----
async function loadTimeline(studentId){
  let d; try{ d=await api('/api/timeline?student_id='+studentId); }catch(e){ return; }
  return d;
}
async function loadReviews(){
  let d; try{ d=await api('/api/reviews'); }catch(e){ return; }
  const el=$('#revTable'); if(!el) return;
  el.innerHTML=d.length? `<table><thead><tr><th>Student</th><th>Date</th><th>Current</th><th>Reason</th><th>Status</th><th></th></tr></thead><tbody>`+d.map(r=>`<tr><td>${r.student_name||r.student_id}</td><td>${r.date}</td><td>${r.current_status||''}</td><td>${r.reason||''}</td><td>${r.status}</td><td>${(state.role==='admin'||state.role==='teacher')&&r.status==='Pending'?`<button class="btn-green" onclick="reviewAction(${r.id},'approve')">Approve</button> <button class="btn-red" onclick="reviewAction(${r.id},'reject')">Reject</button>`:''}</td></tr>`).join('')+`</tbody></table>` : `<div class="muted" style="padding:16px">No review requests.</div>`;
}
async function submitReview(){
  const date=$('#revDate').value, reason=$('#revReason').value;
  if(!date) return toast('Select date',false);
  try{ await api('/api/reviews',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date,reason})}); loadReviews(); toast('Request submitted'); }catch(e){ toast(e.message,false); }
}
async function reviewAction(id, action){
  const ns=action==='approve'? prompt('New status (P/A/L/T):','P') : null;
  if(action==='approve' && !ns) return;
  try{ await api(`/api/reviews?id=${id}&action=${action}&new_status=${ns||''}`,{method:'DELETE'}); loadReviews(); toast('Reviewed'); }catch(e){ toast(e.message,false); }
}
// ---- Mobile + temp QR + public ----
function syncMobileNav(v){
  document.querySelectorAll('#mobileNav button').forEach(b=>b.classList.toggle('active', b.dataset.mview===v));
}
const _origNavigate = navigate;
navigate = function(v){
  syncMobileNav(v);
  // The dedicated Student/Parent portal home (portal.js) replaces the old
  // mobile hero: the hero only knew about the *first* linked child, so for a
  // parent switching children it showed the wrong name.
  return _origNavigate(v);
};
async function renderMobileHero(){ /* superseded by the portal hero in portal.js */ }
async function createTempQR(){
  const payload={class_id:$('#qrTmpClass')?.value||null, section_id:$('#qrTmpSection')?.value||null, subject_id:$('#qrTmpSubject')?.value||null, ttl_minutes:5};
  try{
    const r=await api('/api/qr/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const el=$('#qrTempDisplay');
    if(el) el.innerHTML=`<img src="${BACKEND_URL}/api/qr/image/${r.token}" style="width:200px;height:200px;border:1px solid #e2e8f0;border-radius:12px;background:#fff;padding:8px"><p><b>${r.token}</b></p><small class="muted">Expires ${r.expires_at} • show to class to scan</small>`;
    toast('Temporary QR created (5 min)');
  }catch(e){ toast(e.message,false); }
}
async function scanTempQR(){
  const token=$('#qrTempToken').value.trim(), code=$('#qrTempCode').value.trim();
  if(!token||!code) return toast('Token + Student ID required',false);
  try{
    const r=await api('/api/qr/scan-temp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,code})});
    toast(r.duplicate?'Already marked (no duplicate) ✅':'Marked Present ✅');
  }catch(e){ toast(e.message,false); }
}
window.addEventListener('offline', () => { toast('You are offline — actions will queue', false); });
window.addEventListener('online', () => { toast('Back online'); });
// ---- Android back button (Capacitor App plugin; browser fallback: none) ----
(function setupBackButton(){
  const goBack = () => {
    // close topmost modal first
    const openModal = document.querySelector('.modal.open');
    if(openModal){ openModal.classList.remove('open'); return; }
    const panel = document.getElementById('notifPanel');
    if(panel && !panel.classList.contains('hidden')){ panel.classList.add('hidden'); return; }
    // navigate to dashboard instead of exiting
    const active = document.querySelector('.view.active')?.id;
    if(active && active !== 'view-dashboard'){ navigate('dashboard'); return; }
    if(window.Capacitor?.Plugins?.App){ window.Capacitor.Plugins.App.exitApp(); }
  };
  if(window.Capacitor?.Plugins?.App){
    window.Capacitor.Plugins.App.addListener('backButton', goBack);
  }
  document.addEventListener('backbutton', goBack, false); // Cordova fallback
})();
// ---- Native QR scan bridge (MLKit on Android; manual fallback on web) ----
// Expects QR payload format "ATTEND:<token>" (see /api/qr/image/<token>).
async function scanQRNative(){
  const setToken = (t) => { const el=$('#qrTempToken'); if(el) el.value=t; };
  try{
    const scanning = window.Capacitor?.Plugins?.BarcodeScanning;
    if(!scanning) throw new Error('native-unavailable');
    const perm = await scanning.requestPermissions();
    if(perm.camera !== 'granted'){
      toast('Camera permission denied. Paste the QR token manually.', false);
      return;
    }
    const { barcodes } = await scanning.scan({ hint: 1, formats: [] });
    const raw = (barcodes?.[0]?.displayValue || '').trim();
    const m = raw.match(/ATTEND:([A-Za-z0-9_\-]+)/);
    if(!m){ toast('QR not recognized as attendance code', false); return; }
    setToken(m[1]);
    toast('QR scanned — enter Student ID and Verify');
  }catch(e){
    if(String(e?.message||'').includes('native-unavailable')){
      toast('Native scanner unavailable here — paste the token manually.');
    } else {
      toast('Scan failed: '+(e?.message||e), false);
    }
  }
}
// boot: load login branding + restore session + rememberMe
(async()=>{
  // load login branding (public)
  loadLoginSchoolInfo();
  // rememberMe
  const remembered=localStorage.getItem('rememberUser');
  if(remembered){ const lu=$('#loginUser'); if(lu && !lu.value) lu.value=remembered; }
  try{
    const me=await fetch(BACKEND_URL + '/api/auth/me',{credentials:'same-origin'}).then(r=>r.json());
    if(me && me.user){
      state.currentUser=me.user; state.role=me.user.role;
      $('#loginScreen').style.display='none'; $('#appShell').classList.remove('hidden');
      const portalRole = me.user.role==='student' || me.user.role==='parent';
      if(portalRole && typeof loadPortalMe==='function'){
        try{ await loadPortalMe(); }catch(e){}
        if(typeof portal!=='undefined') portal.mode = me.user.role;
      }
      const who = (portalRole && typeof portalAccountName === 'function')
        ? portalAccountName()
        : me.user.username;
      $('#topName').textContent=who;
      $('#topRole').textContent=me.user.role;
      const pdN=$('#pdName'), pdR=$('#pdRole');
      if(pdN) pdN.textContent=who;
      if(pdR) pdR.textContent=me.user.role+' • Green Valley';
      const dt=$('#dashTeacher'); if(dt) dt.textContent=who;
      filterNavByRole(me.user.role);
      buildMobileNav();
      loadDashboard(); loadClasses(); loadSettings();
    } else {
      try{ await loadClasses(); }catch(e){}
      // honour ?login=student / ?login=parent deep links
      try{
        const want=new URLSearchParams(location.search).get('login');
        if(want && ['student','parent','staff'].includes(want)) showLoginCard(want);
      }catch(e){}
    }
  }catch(e){ try{ await loadClasses(); }catch(e){} }
  // ensure login form Enter works (already via onsubmit)
  applySavedPrefs();
  updateOnlineState();
  window.addEventListener('online', updateOnlineState);
  window.addEventListener('offline', updateOnlineState);
  window.addEventListener('resize', ()=>{ clearTimeout(window._rz); window._rz=setTimeout(()=>buildMobileNav(),200); });
})();

// ============================================================================
// MOBILE SHELL — role-aware bottom navigation, More sheet, sidebar drawer
// ============================================================================
const VIEW_LABELS={
  dashboard:'Dashboard', students:'Students', teachers:'Teachers', classes:'Classes',
  attendance:'Attendance', calendar:'Calendar', reports:'Reports', analytics:'Analytics',
  notices:'Notices', notifications:'Notifications', attcal:'My Attendance', homework:'Homework',
  exams:'Exam Report', profile:'Profile', password:'Change Password', settings:'Settings',
  staff:'Staff', parents:'Parents', messages:'Messages', holidays:'Holidays',
  complaints:'Complaint Box', datesheet:'Date Sheet', timetable:'Timetable', heatmap:'Heatmap',
  studentid:'Student ID', reviews:'Reviews', qr:'QR Attendance', monthly:'Monthly Report',
  enotes:'E-Notes', features:'All Features', meals:'Mid-Day Meal', scholarship:'Scholarship',
  editprofile:'Edit Profile', accountsettings:'Account Settings', privacy:'Privacy & Preferences',
  onboarding:'Complete Profile'
};
const VIEW_ICONS={
  dashboard:'layout-dashboard', students:'graduation-cap', teachers:'user-check', classes:'building-2',
  attendance:'clipboard-check', calendar:'calendar', reports:'file-text', analytics:'chart-column',
  notices:'megaphone', notifications:'bell', attcal:'calendar-days', homework:'notebook-pen',
  exams:'chart-pie', profile:'user', password:'key-round', settings:'settings', staff:'users',
  parents:'user-plus', messages:'message-square', holidays:'calendar', complaints:'circle-alert',
  datesheet:'clipboard-list', timetable:'clock', heatmap:'grid-2x2', studentid:'badge-check',
  reviews:'star', qr:'qr-code', monthly:'table-2', enotes:'book-open', features:'zap',
  meals:'clipboard-list', scholarship:'award',
  editprofile:'pencil', accountsettings:'settings', privacy:'lock', onboarding:'list-checks'
};
// Bottom bar per role: Home, <role items>, More  (per design brief)
const MNAV={
  admin:  [['dashboard','house','Home'],['students','graduation-cap','Students'],['attendance','clipboard-check','Attendance'],['reports','file-text','Reports']],
  teacher:[['dashboard','house','Home'],['attendance','clipboard-check','Attendance'],['reports','file-text','Reports'],['messages','message-square','Messages']],
  student:[['dashboard','house','Home'],['attcal','calendar-days','Attendance'],['enotes','book-open','E-Notes'],['notices','megaphone','Notices']],
  parent: [['dashboard','house','Home'],['attcal','calendar-days','Attendance'],['notices','megaphone','Notices'],['enotes','book-open','E-Notes']]
};
// Everything less-used lives in the More sheet
const MORE_ITEMS={
  admin:['teachers','classes','analytics','notices','notifications','qr','monthly','attcal','homework','exams','calendar','timetable','staff','parents','messages','holidays','complaints','datesheet','heatmap','studentid','reviews','enotes','features','settings','password','profile','editprofile','accountsettings','privacy','onboarding'],
  teacher:['students','classes','notices','notifications','qr','monthly','attcal','homework','exams','calendar','timetable','holidays','complaints','datesheet','studentid','reviews','enotes','features','password','profile','editprofile','accountsettings','privacy','onboarding'],
  student:['reports','homework','exams','datesheet','notifications','calendar','timetable','complaints','reviews','holidays','studentid','features','password','profile','editprofile','accountsettings','privacy','onboarding'],
  parent:['reports','homework','exams','datesheet','notifications','calendar','timetable','complaints','holidays','studentid','features','password','profile','editprofile','accountsettings','privacy','onboarding']
};
function buildMobileNav(){
  const nav=document.getElementById('mobileNav'); if(!nav) return;
  const role=state.role||'teacher';
  const items=(MNAV[role]||MNAV.teacher).filter(([v])=>canView(role,v));
  nav.innerHTML=items.map(([v,ic,label])=>
    `<button data-mview="${v}" type="button" onclick="navigate('${v}')">${icon(ic)}<span>${label}</span></button>`
  ).join('')+`<button data-more type="button" onclick="openMoreSheet()">${icon('ellipsis')}<span>More</span></button>`;
  syncMobileNav(window._currentView||'dashboard');
}
function syncMobileNav(v){
  window._currentView=v;
  const nav=document.getElementById('mobileNav'); if(!nav) return;
  nav.querySelectorAll('button').forEach(b=>{
    b.classList.toggle('active', b.dataset.mview===v);
  });
  // "More" lights up when the active view lives in the sheet
  const more=nav.querySelector('button[data-more]');
  if(more) more.classList.toggle('active', !!nav.querySelector(`button[data-mview="${v}"]`)===false);
}
function openMoreSheet(){
  const role=state.role||'teacher';
  const grid=document.getElementById('moreSheetGrid'); if(!grid) return;
  const primary=new Set((MNAV[role]||MNAV.teacher).map(x=>x[0]));
  const items=(MORE_ITEMS[role]||MORE_ITEMS.teacher)
    .filter(v=>canView(role,v) && !primary.has(v) && document.getElementById('view-'+v));
  grid.innerHTML=items.map(v=>`<button class="sheet-item" type="button" onclick="closeMoreSheet();navigate('${v}')">${icon(VIEW_ICONS[v]||'circle-help')}<span>${VIEW_LABELS[v]||v}</span></button>`).join('');
  document.getElementById('moreSheet')?.classList.add('open');
  paintIcons(grid);
}
function closeMoreSheet(){ document.getElementById('moreSheet')?.classList.remove('open'); }
function closeSidebar(){
  const sb=document.getElementById('sidebar');
  if(sb) sb.classList.remove('open');
  document.getElementById('sidebarScrim')?.classList.remove('show');
}
// The drawer button toggles; the scrim only exists on mobile
(function wireSidebar(){
  const btn=document.getElementById('menuBtn');
  if(btn) btn.onclick=()=>{
    const sb=document.getElementById('sidebar'); if(!sb) return;
    const open=sb.classList.toggle('open');
    document.getElementById('sidebarScrim')?.classList.toggle('show', open);
  };
  // desktop: collapse the rail instead of overlaying it
  document.addEventListener('click',(e)=>{
    if(innerWidth<901) return;
    const head=e.target.closest?.('.sidebar-head');
    if(head) document.getElementById('sidebar')?.classList.toggle('collapsed');
  });
  document.addEventListener('keydown',(e)=>{
    if(e.key==='Escape'){ closeMoreSheet(); closeSidebar(); document.getElementById('profileDrop')?.classList.add('hidden'); }
  });
})();

// ============================================================================
// PREFERENCES — theme, reduced motion, saved login, online indicator
// ============================================================================
function applySavedPrefs(){
  try{
    const theme=localStorage.getItem('curoTheme');
    if(theme) setTheme(theme,true);
    if(localStorage.getItem('curoReduceMotion')==='1') setReduceMotion(true,true);
    if(localStorage.getItem('curoSavedLogin')==='0') setSavedLogin(false,true);
  }catch(e){}
}
function setTheme(t,silent){
  document.documentElement.setAttribute('data-theme',t);
  const m=document.querySelector('meta[name="theme-color"]'); if(m) m.setAttribute('content', t==='dark'?'#0b1220':'#2563eb');
  const cb=$('#setDarkMode'); if(cb) cb.checked = t==='dark';
  try{ if(!silent) localStorage.setItem('curoTheme',t); }catch(e){}
}
function setReduceMotion(on,silent){
  document.documentElement.toggleAttribute('data-reduce-motion', !!on);
  const cb=$('#setReduceMotion'); if(cb) cb.checked=!!on;
  try{ if(!silent) localStorage.setItem('curoReduceMotion', on?'1':'0'); }catch(e){}
}
function setSavedLogin(on,silent){
  const cb=$('#setSavedLogin'); if(cb) cb.checked=!!on;
  if(!on){ try{ localStorage.removeItem('rememberUser'); }catch(e){} }
  try{ if(!silent) localStorage.setItem('curoSavedLogin', on?'1':'0'); }catch(e){}
}
function updateOnlineState(){
  document.body.classList.toggle('is-offline', !navigator.onLine);
  if(!navigator.onLine) toast('You are offline — changes will queue');
}

// ============================================================================
// ATTENDANCE REPORTS (Screen 4) — real server-computed figures
// ============================================================================
let _repRange='daily';
function initReports(){
  const d=$('#repDate'); if(d && !d.value) d.value=new Date().toISOString().slice(0,10);
  const m=$('#repMonth'); if(m && !m.value) m.value=new Date().toISOString().slice(0,7);
  setReportRange(_repRange,true);
  loadReports();
}
function setReportRange(r,silent){
  _repRange=r;
  document.querySelectorAll('#repRange button').forEach(b=>b.classList.toggle('active', b.dataset.range===r));
  const dw=$('#repDateWrap'), mo=$('#repMonth');
  if(dw) dw.classList.toggle('hidden', r!=='daily');
  if(mo) mo.classList.toggle('hidden', r!=='monthly');
  const t=$('#repChartTitle'); if(t) t.textContent = r==='daily'?'Daily Trend': r==='weekly'?'Weekly Trend (last 7 days)':'Monthly Trend (last 6 months)';
  if(!silent) loadReports();
}
function reportNav(dir){
  const d=$('#repDate'); if(!d||!d.value) return;
  const dt=new Date(d.value+'T00:00:00'); dt.setDate(dt.getDate()+dir);
  d.value=dt.toISOString().slice(0,10); loadReports();
}
function exportReport(fmt){
  // Reports reuses the monthly export endpoint so the file matches the on-screen maths
  const month=$('#repMonth')?.value || new Date().toISOString().slice(0,7);
  const cid=$('#repAClass')?.value||'', sid=$('#repASection')?.value||'';
  window.open(`/api/export/monthly/${fmt}?month=${month}&class_id=${cid}&section_id=${sid}`,'_blank');
  toast('Opening '+fmt.toUpperCase()+' export…');
}
function _repSkeleton(){
  ['#repStats','#repClassBars','#repLow','#repHistory','#repCalGrid'].forEach(id=>{
    const el=document.querySelector(id); if(el) el.innerHTML='<div class="sk sk-line"></div><div class="sk sk-line w80"></div><div class="sk sk-line w60"></div>';
  });
}
async function loadReports(){
  const stats=$('#repStats'); if(!stats) return;
  _repSkeleton();
  const cid=$('#repAClass')?.value||'', sid=$('#repASection')?.value||'';
  const qs=`class_id=${cid}&section_id=${sid}`;
  try{
    const day=$('#repDate')?.value || new Date().toISOString().slice(0,10);
    const month=$('#repMonth')?.value || day.slice(0,7);
    const [dash,ana,cal,mon]=await Promise.all([
      api(`/api/attendance/dashboard?date=${day}&${qs}`),
      api(`/api/analytics?${qs}`),
      api(`/api/calendar?month=${month}&${qs}`).catch(()=>null),
      api(`/api/monthly?month=${month}&${qs}`).catch(()=>null)
    ]);
    // 1. stat tiles
    const tiles=[
      ['blue','users','Total',dash.total],
      ['green','circle-check','Present',dash.present],
      ['red','circle-x','Absent',dash.absent],
      ['yellow','clock','Late',dash.late],
      ['yellow','user','Leave',dash.leave],
      ['red','circle-alert','Not Marked',dash.not_marked]
    ];
    stats.innerHTML=tiles.map(([c,ic,label,val])=>
      `<div class="stat-card ${c}"><div class="stat-icon">${icon(ic)}</div><div><small>${label}</small><b>${val??0}</b></div></div>`).join('');
    // 2. donut + legend
    const pct=dash.percentage||0;
    const donut=$('#repDonut');
    if(donut){ donut.style.setProperty('--p', pct); const sp=donut.querySelector('span'); if(sp) sp.innerHTML=pct+'%<small>Attendance</small>'; }
    const pill=$('#repRatePill');
    if(pill){ pill.className='pill '+(pct>=90?'g':pct>=75?'y':'r'); pill.textContent=pct+'% on '+dash.date; }
    const leg=$('#repLegend');
    if(leg) leg.innerHTML=[
      ['g','Present',dash.present],['r','Absent',dash.absent],['y','Late',dash.late],
      ['l','Leave',dash.leave],['n','Not marked',dash.not_marked]
    ].map(([c,l,v])=>`<li><span class="dot ${c}"></span> ${l} <b>${v??0}</b></li>`).join('');
    // 3. trend chart
    const series=_repRange==='weekly'?ana.weekly:_repRange==='monthly'?ana.monthly:ana.weekly;
    const chart=$('#repChart');
    if(chart){
      chart.innerHTML = series.length ? series.map(x=>{
        const label=_repRange==='monthly'?x.month:x.date, pctv=x.percentage||0;
        return `<div style="height:${Math.max(4,pctv)}%" title="${label} — ${pctv}%"><span>${pctv}%</span></div>`;
      }).join('') : '<div class="inline-empty">No data for this range yet.</div>';
    }
    // 4. class-wise bars
    const bars=$('#repClassBars');
    if(bars){
      const comp=ana.class_comparison||[];
      bars.innerHTML = comp.length ? comp.map(c=>{
        const denom=Math.max(1, c.total*ana.working_days||1);
        const p=Math.min(100, Math.round((c.present_records/denom)*100));
        const tone=p>=90?'g':p>=75?'y':'r';
        return `<div class="bar-row"><span class="bar-label">Class ${esc(c.class)}</span>
          <div class="bar-track"><div class="bar-fill ${tone}" style="width:${p}%"></div></div>
          <span class="pct">${p}%</span></div>`;
      }).join('') : '<div class="inline-empty">No classes yet.</div>';
    }
    // 5. low attendance alerts
    const low=$('#repLow');
    if(low){
      const rows=ana.low_attendance||[];
      low.innerHTML = rows.length ? `<table><thead><tr><th>Student</th><th>%</th><th></th></tr></thead><tbody>`+
        rows.map(s=>`<tr><td>${esc(s.name)}<br><small class="muted">${esc(s.student_id)}</small></td>
          <td><span class="badge A">${s.percentage}%</span></td>
          <td><span class="pill warn">Low</span></td></tr>`).join('')+`</tbody></table>`
        : '<div class="inline-empty">No students below 75% this month 🎉</div>';
    }
    // 6. student-wise history — full roster with the server's own monthly maths
    const hist=$('#repHistory');
    if(hist){
      const rows=(mon&&mon.students)||[];
      const wd=(mon&&mon.working_days)||ana.working_days||0;
      hist.innerHTML = rows.length ? `<table><thead><tr><th>Student</th><th>ID</th><th>Present</th><th>Absent</th><th>%</th><th>Status</th></tr></thead><tbody>`+
        rows.map(s=>`<tr><td><b>${esc(s.student.name)}</b><br><small class="muted">Roll ${esc(s.student.roll_no||'—')}</small></td>
          <td class="muted">${esc(s.student.student_id)}</td>
          <td><span class="badge P">${s.present}</span></td>
          <td><span class="badge A">${s.absent}</span></td>
          <td><span class="badge ${s.pct>=90?'P':s.pct>=75?'L':'A'}">${s.pct}%</span></td>
          <td>${s.pct<75?'<span class="pill r">Needs attention</span>':s.pct>=90?'<span class="pill g">Excellent</span>':'<span class="pill y">On track</span>'}</td></tr>`).join('')+`</tbody></table>`
        : '<div class="inline-empty">No students found for this class yet.</div>';
      if(hist.firstChild && wd) hist.dataset.days=wd;
    }
    // 7. calendar
    const grid=$('#repCalGrid');
    if(grid){
      if(!cal || !cal.days){ grid.innerHTML='<div class="inline-empty">No calendar data.</div>'; }
      else{
        const first=new Date(cal.days[0].date+'T00:00:00');
        const lead=(first.getDay()+6)%7; // Monday-first
        let html='';
        for(let i=0;i<lead;i++) html+='<div></div>';
        html+=cal.days.map(d=>{
          const cls=['cal-day'];
          if(d.is_holiday) cls.push('holiday');
          if(d.date===new Date().toISOString().slice(0,10)) cls.push('today');
          const dots=['P','A','L','T'].filter(k=>d[{P:'present',A:'absent',L:'leave',T:'late'}[k]]>0)
            .map(k=>`<i class="cal-dot ${k}"></i>`).join('');
          return `<div class="${cls.join(' ')}" title="${d.date} — ${d.percentage}%">
            <b>${d.date.slice(8)}</b>
            <div class="cal-cell">${d.is_holiday?'Holiday':(d.total?d.percentage+'%':'—')}</div>
            <div>${dots}</div></div>`;
        }).join('');
        grid.innerHTML=html;
      }
    }
  }catch(e){
    stats.innerHTML=`<div class="card error-state" style="grid-column:1/-1">${icon('circle-alert')}<div><b>Could not load reports</b><br><span class="sm">${esc(e.message||e)}</span></div></div>`;
  }
}

// ============================================================================
// DASHBOARD extras — recent activity + command centre toggle
// ============================================================================
async function loadRecentActivity(){
  const el=document.getElementById('recentActivity'); if(!el) return;
  const date=$('#dashDate')?.value || new Date().toISOString().slice(0,10);
  let ana; try{ ana=await api('/api/analytics'); }catch(e){ ana=null; }
  if(!ana || !(ana.class_comparison||[]).length){
    el.innerHTML='<div class="inline-empty">No attendance recorded yet today.</div>'; return;
  }
  const wd=ana.working_days||1;
  el.innerHTML=ana.class_comparison.slice(0,6).map(c=>{
    const p=Math.min(100, Math.round(c.present_records/Math.max(1,c.total*wd)*100));
    const tone=p>=90?'green':p>=75?'yellow':'red';
    const label=p>=90?'Good':p>=75?'Average':'Low';
    return `<div class="list-row" style="cursor:default">
      <div class="ri ${tone}">${icon('clipboard-check')}</div>
      <div class="body"><b>Class ${esc(c.class)}</b><p>${c.total} students on roll</p></div>
      <div style="text-align:right"><span class="badge ${p>=90?'P':p>=75?'L':'A'}">${p}%</span>
        <div class="sm muted" style="margin-top:3px">${label}</div></div>
    </div>`;
  }).join('');
  const d=new Date(date+'T00:00:00');
  const dt=document.getElementById('dashDate');
  if(dt && !isNaN(d)) dt.title='Showing '+d.toLocaleDateString('en-IN',{weekday:'long',day:'2-digit',month:'long',year:'numeric'});
}
function toggleCommandCenter(){
  const cb=document.getElementById('dashHideCC'), card=document.getElementById('ccCard');
  if(!cb||!card) return;
  card.classList.toggle('hidden', cb.checked);
  try{ localStorage.setItem('curoHideCC', cb.checked?'1':'0'); }catch(e){}
}
// restore the command-centre preference as soon as the shell exists
(function initCC(){
  try{
    const cb=document.getElementById('dashHideCC'), card=document.getElementById('ccCard');
    if(cb && card && localStorage.getItem('curoHideCC')==='1'){ cb.checked=true; card.classList.add('hidden'); }
  }catch(e){}
})();

// ============================================================================
// PROFILE MODULE — sign-up, reset, dashboard, edit, settings, privacy, wizard
// ============================================================================
const PF_LANGS=['English','हिन्दी','বাংলা','தமிழ்','తెలుగు','मराठी','ગુજરાતી','ಕನ್ನಡ','മലയാളം','اردو'];

function langOpts(sel){ return PF_LANGS.map(l=>`<option${l===sel?' selected':''}>${esc(l)}</option>`).join(''); }
/* Mirrors the server policy exactly, so the user is not told "saved" only to
   be corrected by an API error a moment later. */
function pwLocalProblem(pw){
  if(pw.length<8) return 'Use at least 8 characters.';
  if(!/[A-Za-z]/.test(pw)) return 'Include at least one letter.';
  if(!/\d/.test(pw)) return 'Include at least one number.';
  return '';
}
function urlLocalProblem(v){
  if(!v) return '';
  if(v.length>200) return 'That link is too long.';
  if(!/^https?:\/\//i.test(v)) return 'Links must start with http:// or https://';
  return '';
}
function showFieldErrors(map, els){
  Object.keys(els||{}).forEach(k=>{
    const box=document.getElementById('err-'+els[k]);
    if(box) box.textContent = map[k] || '';
  });
}
function setMsg(sel, text, ok){
  const el=$(sel); if(!el) return;
  el.textContent = text || '';
  el.classList.toggle('ok', !!ok);
}
function paint(){ try{ paintIcons(); }catch(e){} }

// ---------------------------------------------------------------------------
// Sign up (login screen)
// ---------------------------------------------------------------------------
const SU_EL={full_name:'suName', username:'suUser', email:'suEmail', phone:'suPhone',
             password:'suPass', confirm_password:'suPass2', dob:'suDob',
             language:'suLang', country:'suCountry', accept_terms:'suTerms'};
const SU_EMAIL=/^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$/;

function suClear(){ showFieldErrors({}, SU_EL); setMsg('#suMsg',''); }

async function doSignup(e){
  if(e) e.preventDefault();
  const g=id=>(document.getElementById(id)?.value||'').trim();
  const body={
    full_name:g('suName'), username:g('suUser'), email:g('suEmail'), phone:g('suPhone'),
    password:document.getElementById('suPass').value,
    confirm_password:document.getElementById('suPass2').value,
    dob:g('suDob'), language:g('suLang')||'English', country:g('suCountry'),
    accept_terms:!!document.getElementById('suTerms').checked
  };
  suClear();
  // Client-side first so the obvious mistakes never cost a round trip; the
  // server repeats every one of these plus the uniqueness checks.
  const local={};
  if(body.full_name.length<2) local.full_name='Please enter your full name.';
  if(!/^[A-Za-z0-9][A-Za-z0-9._-]{2,29}$/.test(body.username))
    local.username='Use 3–30 characters: letters, numbers, dot, dash or underscore.';
  if(!SU_EMAIL.test(body.email)) local.email='Enter a valid email address.';
  if(body.phone && !/^\+?\d{7,15}$/.test(body.phone.replace(/[\s()-]/g,'')))
    local.phone='Enter 7–15 digits, optionally starting with +.';
  const pp=pwLocalProblem(body.password); if(pp) local.password=pp;
  if(!local.password && body.confirm_password!==body.password)
    local.confirm_password='The two passwords do not match.';
  if(!body.accept_terms) local.accept_terms='Please accept the Terms of Service and Privacy Policy.';
  if(Object.keys(local).length){ showFieldErrors(local, SU_EL); return; }

  const btn=$('#suBtn'); if(btn){ btn.disabled=true; btn.textContent='Creating account…'; }
  try{
    const r=await fetch(BACKEND_URL+'/api/auth/register',{
      method:'POST', headers:{'Content-Type':'application/json'},
      credentials:'same-origin', body:JSON.stringify(body)});
    const j=await r.json().catch(()=>({}));
    if(!r.ok){
      if(j.fields) showFieldErrors(j.fields, SU_EL);
      setMsg('#suMsg', j.error||'Could not create the account.');
      return;
    }
    suDone(j, body.username);
  }catch(err){
    setMsg('#suMsg','Could not reach the server. Please try again.');
  }finally{
    const b=$('#suBtn'); if(b){ b.disabled=false; b.innerHTML='Create Account '+icon('arrow-right'); paint(); }
  }
}

function suDone(j, username){
  const form=$('#signupForm'); if(!form) return;
  form.innerHTML =
    `<div class="login-role-icon" aria-hidden="true">${icon('circle-check')}</div>
     <h2>Account created</h2>
     <p class="login-sub">${esc(j.message||'Your account is awaiting approval.')}</p>
     <div class="su-done">
       <div class="pf-row"><span>Username</span><b>${esc(username)}</b></div>
       <div class="pf-row"><span>Status</span><b>${esc(j.status||'pending')}</b></div>
     </div>
     ${j.verification_token
       ? `<p class="muted sm">Development mode — no mail server is configured, so the verification token is shown here. In production the school office issues it.</p>
          <div class="field"><label for="suTok">Verification token</label>
          <input id="suTok" readonly value="${escAttr(j.verification_token)}"></div>
          <button class="btn-outline btn-block" type="button" onclick="suVerify()">${icon('shield-check')} Verify my email now</button>`
       : `<p class="muted sm">You will be able to sign in once the school office approves your account.</p>`}
     <p id="suMsg" class="login-msg" role="alert"></p>
     <button class="btn-primary btn-block" type="button" onclick="showLoginCard('staff')">
       ${icon('arrow-left')} Back to sign in</button>`;
  paint();
}

async function suVerify(){
  const t=$('#suTok'); if(!t || !t.value) return;
  try{
    const r=await fetch(BACKEND_URL+'/api/auth/verify-email',{
      method:'POST', headers:{'Content-Type':'application/json'},
      credentials:'same-origin', body:JSON.stringify({token:t.value})});
    const j=await r.json().catch(()=>({}));
    setMsg('#suMsg', (j.message||j.error||'Verification failed.'), !!r.ok);
    if(r.ok){ t.value=''; }
  }catch(e){ setMsg('#suMsg','Could not reach the server.'); }
}

// ---------------------------------------------------------------------------
// Forgot / reset password (login screen)
// ---------------------------------------------------------------------------
let rsStep=1;

function rsReset(){
  rsStep=1;
  $('#rsStep2')?.classList.add('hidden');
  setMsg('#rsMsg','');
  ['rsToken','rsPass','rsPass2'].forEach(id=>{ const e=document.getElementById(id); if(e) e.value=''; });
  const b=$('#rsBtn'); if(b) b.textContent='Continue';
}

async function doResetSubmit(e){
  if(e) e.preventDefault();
  setMsg('#rsMsg','');
  const btn=$('#rsBtn');
  if(rsStep===1){
    const ident=($('#rsIdent')?.value||'').trim();
    if(!ident){ setMsg('#rsMsg','Enter your username or email.'); return; }
    if(btn){ btn.disabled=true; btn.textContent='Working…'; }
    try{
      const r=await fetch(BACKEND_URL+'/api/auth/forgot-password',{
        method:'POST', headers:{'Content-Type':'application/json'},
        credentials:'same-origin', body:JSON.stringify({identifier:ident})});
      const j=await r.json().catch(()=>({}));
      if(!r.ok){ setMsg('#rsMsg', j.error||'Could not start the reset.'); return; }
      rsStep=2;
      $('#rsStep2')?.classList.remove('hidden');
      if(j.dev_token){
        const t=$('#rsToken'); if(t) t.value=j.dev_token;
        setMsg('#rsMsg', (j.message||'')+' (Development mode: the link was filled in for you.)', true);
      }else{
        setMsg('#rsMsg', (j.message||'')+' Ask the school office for the link, then paste it below.');
      }
      if(btn) btn.textContent='Set new password';
    }catch(err){
      setMsg('#rsMsg','Could not reach the server. Please try again.');
    }finally{ if(btn) btn.disabled=false; }
    return;
  }
  const token=($('#rsToken')?.value||'').trim();
  const p=$('#rsPass')?.value||'', p2=$('#rsPass2')?.value||'';
  if(!token){ setMsg('#rsMsg','Paste the reset link or token you were given.'); return; }
  const pp=pwLocalProblem(p); if(pp){ setMsg('#rsMsg',pp); return; }
  if(p!==p2){ setMsg('#rsMsg','The two passwords do not match.'); return; }
  if(btn){ btn.disabled=true; btn.textContent='Saving…'; }
  try{
    const r=await fetch(BACKEND_URL+'/api/auth/reset-password',{
      method:'POST', headers:{'Content-Type':'application/json'},
      credentials:'same-origin', body:JSON.stringify({token, new_password:p, confirm_password:p2})});
    const j=await r.json().catch(()=>({}));
    if(!r.ok){ setMsg('#rsMsg', j.error||'Could not reset the password.'); return; }
    const card=$('#resetForm');
    if(card){
      card.innerHTML =
        `<div class="login-role-icon" aria-hidden="true">${icon('circle-check')}</div>
         <h2>Password updated</h2>
         <p class="login-sub">${esc(j.message||'You can sign in now.')}</p>
         <button class="btn-primary btn-block" type="button" onclick="showLoginCard('staff')">
           ${icon('arrow-left')} Back to sign in</button>`;
      paint();
    }
  }catch(err){
    setMsg('#rsMsg','Could not reach the server. Please try again.');
  }finally{ if(btn) btn.disabled=false; }
}

// ---------------------------------------------------------------------------
// Profile dashboard
// ---------------------------------------------------------------------------
function pfRing(pct){
  return `<div class="pf-ring" style="--p:${Math.max(0,Math.min(100,pct))}"
            role="img" aria-label="Profile ${pct}% complete"><span>${pct}%</span></div>`;
}
function pfRows(rows){
  if(!rows.length) return '<p class="muted">Nothing to show yet.</p>';
  return '<div class="pf-rows">'+rows.map(([k,v])=>
    `<div class="pf-row"><span>${esc(k)}</span><b>${esc(String(v ?? '—'))}</b></div>`).join('')+'</div>';
}
function pfContextCard(ctx, role){
  const rows=[]; let title='Your role';
  if(role==='student'){
    title='My class';
    if(ctx.student){
      rows.push(['Class', (ctx.student.class_name||'—')+' · '+(ctx.student.section_name||'—')]);
      rows.push(['Student ID', ctx.student.student_id||'—']);
      rows.push(['Attendance this month', ctx.attendance_percent+'%']);
    }
  }else if(role==='parent'){
    title='My children';
    (ctx.children||[]).forEach(c=>{
      rows.push([c.name, (c.class_name||'—')+' · '+(c.section_name||'—')]);
      rows.push(['  attendance', c.attendance_percent+'%']);
    });
  }else if(role==='teacher'){
    title='Teaching';
    if(ctx.staff_record){
      rows.push(['Staff record', ctx.staff_record.name||'—']);
      rows.push(['Subject', ctx.staff_record.subject||'—']);
    }else{
      rows.push(['Staff record','Not linked to a teacher profile yet']);
    }
    (ctx.assigned_classes||[]).forEach(c=>
      rows.push(['Assigned class', c.class_name+' · '+c.section_name]));
  }else if(role==='admin'){
    title='School overview';
    rows.push(['School', ctx.school_name||'—']);
    rows.push(['Accounts', ctx.users_total]);
    rows.push(['Awaiting approval', ctx.users_pending]);
  }
  if(!rows.length) return '';
  return `<div class="card"><div class="card-head"><h3>${icon('building-2')} ${esc(title)}</h3></div>
    ${pfRows(rows)}
    ${role==='admin' && ctx.users_pending>0
      ? `<button class="btn-outline" onclick="navigate('accountsettings')">${icon('inbox')} Review pending accounts</button>`:''}
    </div>`;
}

async function loadProfileView(){
  const host=$('#profileCard');
  if(!host) return;
  host.innerHTML='<div class="card"><p class="muted">Loading profile…</p></div>';
  try{
    const d=await api('/api/profile');
    state.profile=d;
    const a=d.account||{}, p=d.profile||{}, comp=d.completion||{percent:0,items:[]};
    const ctx=d.context||{}, role=a.role||state.role||'';
    const photo=p.photo?('/api/photos/'+encodeURIComponent(p.photo)):'';
    const cover=p.cover_photo?('/api/photos/'+encodeURIComponent(p.cover_photo)):'';
    const name=p.display_name||p.full_name||a.username||'';

    const head=`<div class="card pf-head">
      ${cover?`<div class="pf-cover" style="background-image:url('${escAttr(cover)}')"></div>`:''}
      <div class="pf-id">
        <div class="pf-avatar${photo?' has-img':''}"${photo?` style="background-image:url('${escAttr(photo)}')"`:''}>${photo?'':icon('user')}</div>
        <div class="pf-idtext">
          <h3>${esc(name)}</h3>
          <p class="muted">@${esc(a.username)} · User ID ${esc(a.id)}</p>
          <div class="pf-badges">
            <span class="badge">${esc(role)}</span>
            <span class="badge ${a.status==='active'?'P':'A'}">${esc(a.status||'active')}</span>
            ${a.email_verified?`<span class="badge P">Email verified</span>`:`<span class="badge L">Email unverified</span>`}
          </div>
        </div>
        ${pfRing(comp.percent)}
      </div>
      ${comp.percent<100?`<div class="pf-nudge">${icon('zap')}
        <span>Your profile is ${comp.percent}% complete.</span>
        <button class="btn-outline" onclick="navigate('onboarding')">Finish setting up</button></div>`:''}
    </div>`;

    const completion=`<div class="card">
      <div class="card-head"><h3>${icon('list-checks')} Profile completion</h3></div>
      <ul class="pf-checks">${(comp.items||[]).map(i=>
        `<li class="${i.done?'done':''}">${icon(i.done?'circle-check':'circle-help')}
          <span>${esc(i.label)}</span></li>`).join('')}</ul>
      <p class="muted sm">Every item here is optional — nothing personal is required to reach 100%.</p>
    </div>`;

    const actions=`<div class="card">
      <div class="card-head"><h3>${icon('user')} Account</h3></div>
      <div class="pf-actions">
        <button class="btn-primary" onclick="navigate('editprofile')">${icon('pencil')} Edit Profile</button>
        <button class="btn-outline" onclick="navigate('accountsettings')">${icon('settings')} Account Settings</button>
        <button class="btn-outline" onclick="navigate('privacy')">${icon('lock')} Privacy</button>
        <button class="btn-ghost" onclick="logout()">${icon('log-out')} Logout</button>
      </div>
    </div>`;

    host.innerHTML=head+completion+(pfContextCard(ctx,role)||'')+actions;

    // Students/parents keep the guardians + school contact block they had
    // before; it comes from the existing portal endpoint, not a new one.
    if(role==='student'||role==='parent'){
      try{
        const pd=await api('/api/portal/profile'+(childQs()?'?'+childQs().slice(1):''));
        const sch=pd.school||{}, gs=pd.guardians||[];
        host.insertAdjacentHTML('beforeend',
          `<div style="grid-column:1/-1">${childSwitcher()}</div>`+
          profileCard(pd.student)+
          `<div class="card"><div class="card-head"><h3>${icon('users')} Guardians</h3></div>
            <div class="pf-rows">${gs.length?gs.map(g=>
              `<div class="pf-row"><span>${esc(g.parent_id||'Parent')}</span>
                <b>${esc(g.name)}${g.phone?' • '+esc(g.phone):''}</b></div>`).join('')
              :'<p class="muted">No guardian record on file.</p>'}</div>
            <div class="card-head pf-sub">${icon('building-2')} School contact</div>
            <div class="pf-rows">
              <div class="pf-row"><span>School</span><b>${esc(sch.school_name)}</b></div>
              <div class="pf-row"><span>Address</span><b>${esc(sch.address||'—')}</b></div>
              <div class="pf-row"><span>Contact</span><b>${esc(sch.contact||'—')}</b></div>
            </div></div>`);
      }catch(e){ /* the portal block is supplementary; never break the page */ }
    }
  }catch(e){
    host.innerHTML=`<div class="card"><p class="muted">${esc(e.message||e)}</p>
      <button class="btn-outline" onclick="navigate('profile')">${icon('refresh-cw')} Try again</button></div>`;
  }
  paint();
}

// ---------------------------------------------------------------------------
// Edit profile
// ---------------------------------------------------------------------------
const EP_EL={full_name:'epFull', display_name:'epDisplay', dob:'epDob', bio:'epBio'};
const EP_SOCIALS=['instagram','facebook','youtube','linkedin','website','other'];

function epClear(){
  showFieldErrors({}, EP_EL);
  const s=document.getElementById('err-epSocials'); if(s) s.textContent='';
}
function epCount(){
  const b=$('#epBio'), c=$('#epBioCount');
  if(b&&c) c.textContent=b.value.length;
}
async function epLoad(){
  try{
    const d=await api('/api/profile');
    state.profile=d;
    const p=d.profile||{}, s=p.socials||{};
    const set=(id,v)=>{ const e=document.getElementById(id); if(e) e.value=v??''; };
    set('epFull',p.full_name); set('epDisplay',p.display_name);
    set('epDob',p.dob); set('epGender',p.gender); set('epPronouns',p.pronouns);
    set('epCity',p.city); set('epCountry',p.country);
    set('epLang',p.language||'English');
    set('epBio',p.bio); set('epInterests',p.interests);
    EP_SOCIALS.forEach(k=>set('ep'+k.charAt(0).toUpperCase()+k.slice(1), s[k]));
    epPhotoCard(); epCount(); epClear();
  }catch(e){ toast(e.message||'Could not load profile', false); }
  paint();
}
async function epPhotoCard(){
  const host=$('#epPhotoCard'); if(!host) return;
  const d=state.profile||await api('/api/profile');
  const p=d.profile||{};
  const src=p.photo?('/api/photos/'+encodeURIComponent(p.photo)):'';
  host.innerHTML=`<div class="card-head"><h3>${icon('camera')} Profile photo</h3></div>
    <div class="pf-photo-row">
      <div class="pf-avatar lg${src?' has-img':''}"${src?` style="background-image:url('${escAttr(src)}')"`:''}>${src?'':icon('user')}</div>
      <div>
        <p class="muted sm">JPEG, PNG or WebP, up to 2 MB. Images are re-encoded
          on the server, which also strips location data from the file.</p>
        <div class="pf-actions">
          <button class="btn-outline" onclick="epPick('/api/profile/photo')">${icon('camera')} ${src?'Change photo':'Upload photo'}</button>
          ${src?`<button class="btn-ghost" onclick="epRemove('/api/profile/photo')">${icon('trash-2')} Remove</button>`:''}
        </div>
      </div>
    </div>`;
  paint();
}
function epPick(route){
  const inp=document.createElement('input');
  inp.type='file'; inp.accept='image/png,image/jpeg,image/webp';
  inp.onchange=()=>epUpload(route, inp.files&&inp.files[0]);
  inp.click();
}
async function epUpload(route, file){
  if(!file) return;
  if(file.size>2*1024*1024){ toast('Images must be 2 MB or smaller', false); return; }
  const fd=new FormData(); fd.append('image', file);
  try{
    const r=await fetch(BACKEND_URL+route,{method:'POST',credentials:'same-origin',body:fd});
    const j=await r.json().catch(()=>({}));
    if(!r.ok){ toast(j.error||'Could not upload that image', false); return; }
    toast('Photo updated');
    if(typeof epPhotoCard==='function') epPhotoCard();
    if($('#profileCard')) loadProfileView();
  }catch(e){ toast('Could not reach the server', false); }
}
async function epRemove(route){
  try{
    const r=await fetch(BACKEND_URL+route,{method:'DELETE',credentials:'same-origin'});
    const j=await r.json().catch(()=>({}));
    if(!r.ok){ toast(j.error||'Could not remove the image', false); return; }
    toast('Image removed');
    epPhotoCard();
    if($('#profileCard')) loadProfileView();
  }catch(e){ toast('Could not reach the server', false); }
}
async function epSave(){
  epClear();
  const g=id=>(document.getElementById(id)?.value||'').trim();
  const socials={};
  EP_SOCIALS.forEach(k=>{ socials[k]=g('ep'+k.charAt(0).toUpperCase()+k.slice(1)); });
  const local={};
  if(g('epFull').length<2) local.full_name='Please enter your full name.';
  if(g('epBio').length>280) local.bio='Keep your bio under 280 characters.';
  const badSocial=EP_SOCIALS.map(k=>urlLocalProblem(socials[k])).find(Boolean);
  if(badSocial) local.socials=badSocial;
  if(Object.keys(local).length){ showFieldErrors(local, EP_EL);
    const s=document.getElementById('err-epSocials'); if(s) s.textContent=local.socials||''; return; }

  const body={full_name:g('epFull'), display_name:g('epDisplay'), dob:g('epDob'),
    gender:g('epGender'), pronouns:g('epPronouns'), city:g('epCity'),
    country:g('epCountry'), language:g('epLang'), bio:g('epBio'),
    interests:g('epInterests'), socials};
  const btn=$('#epSaveBtn'); if(btn){ btn.disabled=true; btn.textContent='Saving…'; }
  try{
    const d=await api('/api/profile',{method:'PUT',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if(d.fields) showFieldErrors(d.fields, EP_EL);
    setMsg('#epMsg', d.message||'Profile saved.', true);
    toast('Profile saved');
    state.profile=null;
    if($('#profileCard')) loadProfileView();
  }catch(e){
    if(e.body && e.body.fields) showFieldErrors(e.body.fields, EP_EL);
    setMsg('#epMsg', e.message||'Could not save the profile.');
  }finally{ const b=$('#epSaveBtn'); if(b){ b.disabled=false;
    b.innerHTML=icon('shield-check')+' Save Changes'; paint(); } }
}

// ---------------------------------------------------------------------------
// Account settings
// ---------------------------------------------------------------------------
async function asLoad(){
  try{
    const d=await api('/api/profile');
    state.profile=d;
    const a=d.account||{}, p=d.profile||{};
    const host=$('#asAccount');
    if(host){
      host.innerHTML=`<div class="card-head"><h3>${icon('user')} Sign-in details</h3></div>
        <div class="grid-2">
          <div class="field"><label for="asUser">Username</label>
            <input id="asUser" maxlength="30" value="${escAttr(a.username)}" autocomplete="username">
            <p class="field-err" id="err-asUser"></p></div>
          <div class="field"><label for="asEmail">Email address</label>
            <input id="asEmail" type="email" maxlength="254" value="${escAttr(a.email||'')}" autocomplete="email">
            <p class="field-err" id="err-asEmail"></p></div>
          <div class="field"><label for="asPhone">Mobile number</label>
            <input id="asPhone" type="tel" maxlength="20" value="${escAttr(a.phone||'')}" autocomplete="tel">
            <p class="field-err" id="err-asPhone"></p></div>
          <div class="field"><label for="asLang">Preferred language</label>
            <select id="asLang">${langOpts(p.language||'English')}</select></div>
        </div>
        <p class="muted sm">Changing your username changes what you type at the sign-in screen.</p>
        <button class="btn-primary" id="asSaveBtn" onclick="asSave()">${icon('shield-check')} Save Changes</button>`;
      paint();
    }
    asSessions();
  }catch(e){ toast(e.message||'Could not load account settings', false); }
}
async function asSave(){
  ['asUser','asEmail','asPhone'].forEach(id=>{
    const b=document.getElementById('err-'+id); if(b) b.textContent='';
  });
  const g=id=>(document.getElementById(id)?.value||'').trim();
  const body={username:g('asUser'), email:g('asEmail'), phone:g('asPhone'),
              language:g('asLang')};
  const local={};
  if(!/^[A-Za-z0-9][A-Za-z0-9._-]{2,29}$/.test(body.username))
    local.username='Use 3–30 characters: letters, numbers, dot, dash or underscore.';
  if(!SU_EMAIL.test(body.email)) local.email='Enter a valid email address.';
  if(body.phone && !/^\+?\d{7,15}$/.test(body.phone.replace(/[\s()-]/g,'')))
    local.phone='Enter 7–15 digits, optionally starting with +.';
  if(Object.keys(local).length){ showFieldErrors(local,{username:'asUser',email:'asEmail',phone:'asPhone'}); return; }
  const btn=$('#asSaveBtn'); if(btn){ btn.disabled=true; btn.textContent='Saving…'; }
  try{
    const d=await api('/api/profile',{method:'PUT',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if(d.fields) showFieldErrors(d.fields,{username:'asUser',email:'asEmail',phone:'asPhone'});
    setMsg('#asMsg', d.message||'Saved.', true);
    toast('Account updated');
  }catch(e){
    if(e.body && e.body.fields)
      showFieldErrors(e.body.fields,{username:'asUser',email:'asEmail',phone:'asPhone'});
    setMsg('#asMsg', e.message||'Could not save.');
  }finally{ const b=$('#asSaveBtn'); if(b){ b.disabled=false;
    b.innerHTML=icon('shield-check')+' Save Changes'; paint(); } }
}
async function asSessions(){
  const host=$('#asSessions'); if(!host) return;
  try{
    const d=await api('/api/profile/sessions');
    const rows=d.sessions||[];
    host.innerHTML=rows.length?rows.map(x=>{
      const t=String(x.time||'').replace('T',' ').slice(0,16);
      return `<div class="pf-row"><span>${esc(t)}</span>
        <b class="${x.success?'ok':''}">${x.success?'Successful':'Failed attempt'}</b></div>`;
    }).join(''):'<p class="muted">No sign-ins recorded yet.</p>';
  }catch(e){ host.innerHTML='<p class="muted">Sign-in history unavailable.</p>'; }
}
async function asLogoutOthers(){
  const btn=$('#asLogoutOthers'); if(btn){ btn.disabled=true; btn.textContent='Signing out…'; }
  try{
    const d=await api('/api/profile/logout-others',{method:'POST'});
    setMsg('#asMsg', d.message||'Done.', true);
    toast('Other devices signed out');
    asSessions();
  }catch(e){ setMsg('#asMsg', e.message||'Could not sign out other devices.'); }
  finally{ const b=$('#asLogoutOthers'); if(b){ b.disabled=false;
    b.innerHTML=icon('log-out')+' Sign out other devices'; paint(); } }
}

// ---------------------------------------------------------------------------
// Privacy & preferences
// ---------------------------------------------------------------------------
function pvToggle(key,label,on){
  return `<label class="toggle-row"><span>${esc(label)}</span>
    <input type="checkbox" data-pvkey="${escAttr(key)}"${on?'checked':''} onchange="pvSave()"></label>`;
}
async function pvLoad(){
  try{
    const d=await api('/api/profile');
    state.profile=d;
    const p=d.profile||{};
    const vis=$('#pvVisibility');
    if(vis){
      vis.innerHTML=`<div class="card-head"><h3>${icon('lock')} Profile visibility</h3></div>
        <p class="muted sm">A public profile opens only for someone who already
          knows your exact username — there is no directory and no search — and
          it never reveals your role, class or attendance.</p>
        <div class="field"><label for="pvVis">Who can view your profile</label>
          <select id="pvVis" onchange="pvSave()">
            <option value="private">Only me (default)</option>
            <option value="public">Anyone who has my username</option>
          </select></div>
        <div class="toggle-list" id="pvShow">
          ${pvToggle('show_email','Show my email address',p.show_email)}
          ${pvToggle('show_phone','Show my mobile number',p.show_phone)}
          ${pvToggle('show_dob','Show my date of birth',p.show_dob)}
        </div>`;
      const v=$('#pvVis'); if(v) v.value=p.visibility==='public'?'public':'private';
      paint();
    }
    $('#pvNotify').innerHTML=
      pvToggle('notify_email','Email notifications',p.notify_email)+
      pvToggle('notify_app','In-app notifications',p.notify_app)+
      pvToggle('notify_attendance','Attendance updates',p.notify_attendance)+
      pvToggle('notify_notices','New notices',p.notify_notices);
    $('#pvA11y').innerHTML=
      pvToggle('a11y_large_text','Larger text',p.a11y_large_text)+
      pvToggle('a11y_reduced_motion','Reduce motion',p.a11y_reduced_motion);
    const th=$('#pvTheme'); if(th) th.value=p.theme||'light';
    pvDeleteCard();
    const admin=$('#pvAdmin');
    if(d.can && d.can.manage_users) pvAdminList(); else if(admin) admin.classList.add('hidden');
  }catch(e){ toast(e.message||'Could not load privacy settings', false); }
  paint();
}
async function pvSave(){
  const body={};
  document.querySelectorAll('[data-pvkey]').forEach(i=>{ body[i.dataset.pvkey]=i.checked; });
  const v=$('#pvVis'); if(v) body.visibility=v.value;
  const t=$('#pvTheme'); if(t) body.theme=t.value;
  try{
    const d=await api('/api/profile',{method:'PUT',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    setMsg('#pvMsg', d.message||'Preferences saved.', true);
  }catch(e){ setMsg('#pvMsg', e.message||'Could not save preferences.'); }
}
async function pvDeleteCard(){
  const host=$('#pvDelete'); if(!host) return;
  try{
    const d=await api('/api/profile/delete-request');
    if(d.request){
      const t=String(d.request.created_at||'').replace('T',' ').slice(0,16);
      host.innerHTML=`<p class="muted">You already have a request pending
        (sent ${esc(t)}). The school office will review it — nothing has been removed yet.</p>`;
      return;
    }
    host.innerHTML=`<p class="muted sm">This asks the school office to close your
      login. It never deletes attendance, marks or any other school record, and
      nothing is removed until an admin approves it.</p>
      <div class="field"><label for="pvReason">Reason <small class="muted">(optional)</small></label>
        <textarea id="pvReason" rows="2" maxlength="300"></textarea></div>
      <div class="field"><label for="pvConfirm">Type <b>DELETE</b> to confirm *</label>
        <input id="pvConfirm" placeholder="DELETE" autocomplete="off"></div>
      <button class="btn-red" onclick="pvDeleteRequest()">${icon('trash-2')} Request account deletion</button>`;
    paint();
  }catch(e){ host.innerHTML='<p class="muted">Could not load this section.</p>'; }
}
async function pvDeleteRequest(){
  const why=(document.getElementById('pvConfirm')?.value||'').trim();
  if(why!=='DELETE'){ setMsg('#pvMsg','Type DELETE to confirm the request.'); return; }
  try{
    const d=await api('/api/profile/delete-request',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({confirm:why, reason:(document.getElementById('pvReason')?.value||'').trim()})});
    setMsg('#pvMsg', d.message||'Request sent.', true);
    toast('Deletion request sent');
    pvDeleteCard();
  }catch(e){ setMsg('#pvMsg', e.message||'Could not send the request.'); }
}
async function pvAdminList(){
  const card=$('#pvAdmin'), host=$('#pvAdminList');
  if(!card||!host) return;
  card.classList.remove('hidden');
  try{
    const rows=await api('/api/account-deletions');
    const pending=rows.filter(r=>r.status==='pending');
    host.innerHTML=pending.length?pending.map(r=>
      `<div class="list-row">
        <div class="ri">${icon('inbox')}</div>
        <div class="body"><b>${esc(r.username)}</b>
          <p>${esc(r.reason||'No reason given')} · ${esc(String(r.created_at||'').replace('T',' ').slice(0,16))}</p></div>
        <div class="pf-actions">
          <button class="btn-outline" onclick="pvAdminDecide(${r.id},'rejected')">${icon('circle-x')} Reject</button>
          <button class="btn-red" onclick="pvAdminDecide(${r.id},'approved')">${icon('trash-2')} Approve</button>
        </div>
      </div>`).join(''):'<p class="muted">No pending deletion requests.</p>';
    paint();
  }catch(e){ host.innerHTML='<p class="muted">Could not load requests.</p>'; }
}
async function pvAdminDecide(id, decision){
  try{
    const d=await api('/api/account-deletions',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id, decision})});
    setMsg('#pvMsg', 'Request '+(d.status||decision)+'.', true);
    toast('Request '+decision);
    pvAdminList();
  }catch(e){ setMsg('#pvMsg', e.message||'Could not update the request.'); }
}

// ---------------------------------------------------------------------------
// Onboarding wizard
// ---------------------------------------------------------------------------
const OB_TOTAL=3;
const OB_TITLES=['Your photo & name','A little about you','Interests & preferences'];
let obStep=0;

function obLoad(){ obStep=0; obRender(); }
function obRender(){
  const d=state.profile||{}, p=d.profile||{}, comp=d.completion||{percent:0,items:[]};
  const steps=$('#obSteps');
  if(steps){
    steps.innerHTML=OB_TITLES.map((t,i)=>
      `<button type="button" class="ob-step${i===obStep?' active':''}${i<obStep?' done':''}"
        onclick="obJump(${i})"><span>${i+1}</span>${esc(t)}</button>`).join('');
  }
  const src=p.photo?('/api/photos/'+encodeURIComponent(p.photo)):'';
  const body=$('#obBody');
  if(!body) return;
  if(obStep===0){
    body.innerHTML=`<div class="card-head"><h3>${icon('camera')} Photo &amp; display name</h3></div>
      <div class="pf-photo-row">
        <div class="pf-avatar lg${src?' has-img':''}"${src?` style="background-image:url('${escAttr(src)}')"`:''}>${src?'':icon('user')}</div>
        <div>
          <div class="pf-actions">
            <button class="btn-outline" onclick="epPick('/api/profile/photo')">${icon('camera')} ${src?'Change photo':'Upload photo'}</button>
            ${src?`<button class="btn-ghost" onclick="epRemove('/api/profile/photo').then(obRender)">${icon('trash-2')} Remove</button>`:''}
          </div>
          <p class="muted sm">Optional, and it never has to be a real photo of you.</p>
        </div>
      </div>
      <div class="field"><label for="obDisplay">Display name</label>
        <input id="obDisplay" maxlength="60" value="${escAttr(p.display_name||'')}"
          placeholder="How you want to appear">
        <p class="field-err" id="err-obDisplay"></p></div>`;
  }else if(obStep===1){
    body.innerHTML=`<div class="card-head"><h3>${icon('pencil')} About you</h3></div>
      <div class="field"><label for="obBio">Bio</label>
        <textarea id="obBio" rows="3" maxlength="280"
          placeholder="A line or two about you">${esc(p.bio||'')}</textarea>
        <p class="muted sm"><span id="obBioCount">${(p.bio||'').length}</span>/280</p>
        <p class="field-err" id="err-obBio"></p></div>
      <div class="field"><label for="obInterests">Interests &amp; hobbies</label>
        <textarea id="obInterests" rows="2" maxlength="300"
          placeholder="Chess, cricket, reading…">${esc(p.interests||'')}</textarea></div>`;
    const b=$('#obBio'); if(b) b.oninput=()=>{ const c=$('#obBioCount'); if(c) c.textContent=b.value.length; };
  }else{
    const s=p.socials||{};
    body.innerHTML=`<div class="card-head"><h3>${icon('send')} One social link &amp; preferences</h3></div>
      <p class="muted sm">Add a single link — that is all this step needs.</p>
      <div class="grid-2">
        <div class="field"><label for="obWebsite">Website or portfolio</label>
          <input id="obWebsite" type="url" maxlength="200" value="${escAttr(s.website||'')}"
            placeholder="https://example.com"><p class="field-err" id="err-obWebsite"></p></div>
        <div class="field"><label for="obLang">Preferred language</label>
          <select id="obLang">${langOpts(p.language||'English')}</select></div>
        <div class="field"><label for="obTheme">Theme</label>
          <select id="obTheme">
            <option value="light"${p.theme!=='dark'?' selected':''}>Light</option>
            <option value="dark"${p.theme==='dark'?' selected':''}>Dark</option>
          </select></div>
      </div>`;
  }
  const bk=$('#obBack'), nx=$('#obNext');
  if(bk) bk.innerHTML=obStep===0?icon('arrow-left')+' Back to profile':icon('arrow-left')+' Back';
  if(nx) nx.innerHTML=obStep===OB_TOTAL-1
    ? 'Finish '+icon('circle-check') : 'Next '+icon('arrow-right');
  const comp2=state.profile&&state.profile.completion;
  if(comp2) setMsg('#obMsg','Profile '+comp2.percent+'% complete', comp2.percent===100);
  paint();
}
async function obJump(i){
  if(i>obStep){ // moving forward still saves what is on screen now
    const err=await obSave(); if(err) return;
  }
  obStep=Math.max(0,Math.min(OB_TOTAL-1,i)); obRender();
}
async function obSave(){
  const body={};
  if(obStep===0){
    const v=(document.getElementById('obDisplay')?.value||'').trim();
    if(v){ body.display_name=v; }
  }else if(obStep===1){
    body.bio=(document.getElementById('obBio')?.value||'').trim();
    body.interests=(document.getElementById('obInterests')?.value||'').trim();
    if(body.bio.length>280){ showFieldErrors({bio:'Keep your bio under 280 characters.'},{bio:'obBio'}); return true; }
  }else{
    const w=(document.getElementById('obWebsite')?.value||'').trim();
    const bad=urlLocalProblem(w);
    if(bad){ const e=document.getElementById('err-obWebsite'); if(e) e.textContent=bad; return true; }
    body.socials={website:w};
    const l=document.getElementById('obLang'); if(l) body.language=l.value;
    const t=document.getElementById('obTheme'); if(t) body.theme=t.value;
  }
  try{
    const d=await api('/api/profile',{method:'PUT',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if(d.fields){ showFieldErrors(d.fields,{display_name:'obDisplay',bio:'obBio'}); return true; }
    state.profile=Object.assign({}, state.profile||{}, {profile:d.profile, completion:d.completion});
    return false;
  }catch(e){
    setMsg('#obMsg', e.message||'Could not save this step.');
    return true;
  }
}
async function obMove(dir){
  setMsg('#obMsg','');
  if(dir<0){
    if(obStep===0){ navigate('profile'); return; }
    obStep--; obRender(); return;
  }
  const err=await obSave(); if(err) return;
  if(obStep<OB_TOTAL-1){ obStep++; obRender(); return; }
  toast('Profile setup finished');
  const d=await api('/api/profile').catch(()=>null);
  if(d){ state.profile=d; }
  navigate('profile');
}


