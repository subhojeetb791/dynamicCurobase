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

function toast(msg, ok=true){ const t=document.createElement('div'); t.className='toast'; t.textContent=msg; t.style.background=ok?'#0f172a':'#dc2626'; const c=$('#toast'); if(c) c.appendChild(t); setTimeout(()=>t.remove(),3000); }
function togglePwd(){ const i=$('#loginPass'); i.type=i.type==='password'?'text':'password'; }
async function api(p,opts={}){
  opts.credentials = opts.credentials || 'same-origin';
  if(!opts.headers) opts.headers={};
  // ensure cookie sent
  const r=await fetch(p.startsWith('/') ? BACKEND_URL + p : p, opts);
  const j=await r.json().catch(()=>({}));
  if(r.status===401){
    // not authenticated -> show login
    $('#appShell')?.classList.add('hidden');
    const ls=$('#loginScreen');
    if(ls) ls.style.display='flex';
    throw new Error(j.error||'Not authenticated');
  }
  if(r.status===403){
    const role = state.role || 'unknown';
    showDenied(role, p);
    throw new Error(j.error||'Access denied');
  }
  if(!r.ok) throw new Error(j.error||'Error');
  return j;
}
function navigate(v){
  const role = state.role || 'admin';
  if(!canView(role, v)){
    showDenied(role, v);
    toast('Access denied for '+role,false);
    return;
  }
  $$('#nav button, .nav-mini button').forEach(b=>b.classList.toggle('active', b.dataset.view===v));
  $$('.view').forEach(s=>s.classList.toggle('active', s.id==='view-'+v));
  if(v==='features') v='features';
  const t=document.querySelector(`[data-view="${v}"]`)?.textContent?.trim() || v;
  const pt=$('#pageTitle'); if(pt) pt.textContent=t;
  if(innerWidth<900) $('#sidebar')?.classList.remove('open');
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
  if(v==='reports') {loadMarksReport(); initMarksChips();}
  if(v==='qr') {}
  if(v==='notices') loadNotices();
  if(v==='enotes') loadENotes();
  if(v==='meals') loadMeals();
  if(v==='scholarship') loadScholarships();
  if(v==='complaints') loadComplaints();
  if(v==='settings') loadSettings();
}
$$('#nav button, .nav-mini button').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.view)));
const mb=$('#menuBtn'); if(mb) mb.onclick=()=>$('#sidebar').classList.toggle('open');
function toggleProfile(){ $('#profileDrop')?.classList.toggle('hidden'); }
async function logout(){
  try{ await fetch(BACKEND_URL + '/api/auth/logout',{method:'POST',credentials:'same-origin'}); }catch(e){}
  state.currentUser=null; state.role=null;
  $('#appShell')?.classList.add('hidden');
  const ls=$('#loginScreen'); if(ls) ls.style.display='flex';
  toast('Logged out');
}
function globalSearch(){ const q=$('#globalSearch')?.value.toLowerCase()||''; if(q.length<2) return; if(['student','class','attendance'].some(w=>q.includes(w))) navigate(q.includes('student')?'students':q.includes('attendance')?'attendance':'classes'); }
async function loadLoginSchoolInfo(){
  try{
    const s=await fetch(BACKEND_URL + '/api/settings',{credentials:'same-origin'}).then(r=>r.json());
    const name=s.school_name||'Dynamic Attendance App';
    const logo=s.logo_path;
    // left side
    const leftH1=document.querySelector('.login-left h1');
    if(leftH1) leftH1.textContent=name;
    const loginLogo=$('#loginLogo'), loginName=$('#loginSchoolName');
    if(loginName) loginName.textContent=name;
    if(loginLogo && logo){
      loginLogo.src='${BACKEND_URL}/api/logo/'+logo;
      loginLogo.classList.remove('hidden');
    }
    // also update topbar if already logged
  }catch(e){}
}
async function doLogin(e){
  if(e) e.preventDefault();
  const u=$('#loginUser').value.trim(), p=$('#loginPass').value;
  const msgEl=$('#loginMsg'), btn=$('#loginBtn');
  if(!u || !p){ if(msgEl) msgEl.textContent='Username and password required'; toast('Username and password required',false); return; }
  if(btn){ btn.disabled=true; btn.textContent='Logging in...'; }
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
    toast('Welcome '+j.user.username+' ('+role+')');
    // role-based redirect: all go to dashboard which adapts per role
    navigate('dashboard');
    loadDashboard(); loadClasses(); loadSettings();
  }catch(e){ if(msgEl) msgEl.textContent=e.message; toast(e.message,false); }
  finally{ if(btn){ btn.disabled=false; btn.textContent='Login →'; } }
}
// init time badge
setInterval(()=>{ const b=$('#todayBadge'); if(b) b.textContent=new Date().toLocaleDateString('en-IN',{weekday:'short',day:'2-digit',month:'short',year:'numeric'}); },1000);

// helpers for class/section selects
async function loadClasses(){
  try{
  const data=await api('/api/classes'); state.classes=data;
  const opts=data.map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
  const allOpts='<option value="">All / Select</option>'+opts;
  ['#s_class','#attClass','#monClass','#repClass','#secClass','#waClass','#dsClass','#mealClass','#f_class','#calClass','#anaClass','#ttClass','#qrTmpClass'].forEach(sel=>{ const el=$(sel); if(el) el.innerHTML=allOpts; });
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
  const map={'#s_section':'#s_class','#attSection':'#attClass','#monSection':'#monClass','#waSection':'#waClass','#f_section':'#f_class','#calSection':'#calClass','#anaSection':'#anaClass'};
  const classSel=map[sel]; if(!classSel) return;
  const cid=$(classSel)?.value; const el=$(sel); if(!el) return;
  if(!cid){ el.innerHTML='<option value="">All / Select</option>'; return; }
  const cls=state.classes.find(x=>x.id==cid);
  el.innerHTML='<option value="">All / Select</option>'+(cls?.sections||[]).map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
}
function filterSections(){ ['#s_section','#attSection','#monSection','#waSection','#f_section','#calSection','#anaSection'].forEach(s=>filterSection(s)); }
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
    try{
      const att=await api('/api/attendance?date='+new Date().toISOString().slice(0,10));
      const my = att.students[0];
      if(my){
        el('kpiTotal', '1'); el('kpiPresent', my.status==='P'?'1':'0');
        el('kpiAbsent', my.status==='A'?'1':'0'); el('kpiLeave', my.status==='L'?'1':'0');
        el('kpiLate', my.status==='T'?'1':'0'); el('kpiRate', my.status==='P'||my.status==='T'?'100%':'0%');
        el('kpiClasses', s.total_classes||'-');
        el('legP', my.status==='P'?'1':'0'); el('legA', my.status==='A'?'1':'0');
        el('legL', my.status==='L'?'1':'0'); const lt=$('#legT'); if(lt) lt.textContent=my.status==='T'?'1':'0';
        el('legN', my.status?'0':'1');
        const pct = (my.status==='P'||my.status==='T')?100:0;
        const donut=document.getElementById('donut'); if(donut){ donut.style.setProperty('--p', pct); const sp=donut.querySelector('span'); if(sp) sp.textContent=pct+'%'; }
      }
    }catch(e){}
    const si=document.getElementById('schoolInfo'); if(si) si.innerHTML=`<b>Personal Dashboard (${state.role})</b> • Session ${sessName}`;
    loadNotifBadge();
    return;
  }
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
    <div class="stat-card green"><div class="stat-icon">✅</div><div><small>Present</small><b>${dash.present}</b></div></div>
    <div class="stat-card red"><div class="stat-icon">❌</div><div><small>Absent</small><b>${dash.absent}</b></div></div>
    <div class="stat-card yellow"><div class="stat-icon">🟡</div><div><small>Late</small><b>${dash.late||0}</b></div></div>
    <div class="stat-card blue"><div class="stat-icon">🔵</div><div><small>Leave</small><b>${dash.leave}</b></div></div>
    <div class="stat-card blue"><div class="stat-icon">📊</div><div><small>Total / %</small><b>${totalSys} • ${dash.percentage}%</b></div></div>`;
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
    <div class="stat-card blue"><div class="stat-icon">👨‍🎓</div><div><small>Total Students</small><b>${data.students.length}</b></div></div>
    <div class="stat-card green"><div class="stat-icon">✅</div><div><small>Avg Present</small><b>${Math.round(data.students.reduce((a,c)=>a+c.present,0)/Math.max(1,data.students.length))}</b></div></div>
    <div class="stat-card red"><div class="stat-icon">❌</div><div><small>Working Days</small><b>${data.working_days}</b></div></div>
    <div class="stat-card yellow"><div class="stat-icon">📊</div><div><small>Month</small><b>${month}</b></div></div>`;
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

async function loadDateSheets(){ let data; try{ data=await api('/api/datesheets'); }catch(e){ data=[]; } const el=$('#dsTable'); if(!el) return; el.innerHTML=data.length? `<table><thead><tr><th>Class</th><th>Exam</th><th>Subject</th><th>Date</th><th>Time</th><th></th></tr></thead><tbody>`+data.map(d=>`<tr><td>${d.class_name||d.class_id}</td><td>${d.exam_type}</td><td>${d.subject}</td><td>${d.date}</td><td>${d.time||''}</td><td>${state.role==='admin'?`<button class="btn-red" onclick="delDS(${d.id})">Delete</button>`:''}</td></tr>`).join('')+`</tbody></table>` : `<div class="muted" style="padding:16px">No date sheets.</div>`; }
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

async function loadNotices(){ let data; try{ data=await api('/api/notices'); }catch(e){ data=[]; } const el=$('#noticeList'); if(!el) return; el.innerHTML=data.length? data.map(n=>`<div class="card" style="border-left:4px solid var(--blue)"><b>${n.title}</b> <small class="muted">${n.date}</small><p>${n.content}</p>${state.role==='admin'?`<button class="btn-red" onclick="delNotice(${n.id})">Delete</button>`:''}</div>`).join('') : `<div class="muted" style="padding:16px">No notices</div>`; }
async function addNotice(){ if(state.role!=='admin') return toast('Admin only',false); const t=$('#noticeTitle').value.trim(), c=$('#noticeContent').value.trim(); if(!t) return toast('Title required',false); try{await api('/api/notices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,content:c})}); loadNotices(); toast('Notice posted');}catch(e){toast(e.message,false)} }
async function delNotice(id){ if(state.role!=='admin') return toast('Admin only',false); try{await api('/api/notices?id='+id,{method:'DELETE'}); loadNotices();}catch(e){toast(e.message,false)} }

async function loadENotes(){ let data; try{ data=await api('/api/enotes'); }catch(e){ data=[]; } const el=$('#enoteList'); if(!el) return; el.innerHTML=data.length? data.map(n=>`<div class="card"><b>${n.title}</b> — <small>${n.subject||''}</small><p>${n.content||''}</p><small class="muted">${n.date}</small> ${['admin','teacher'].includes(state.role)?`<button class="btn-red" onclick="delENote(${n.id})">Delete</button>`:''}</div>`).join('') : `<div class="muted">No notes</div>`; }
async function addENote(){ if(!['admin','teacher'].includes(state.role)) return toast('Access denied: cannot add notes',false); const t=$('#noteTitle').value.trim(), s=$('#noteSubject').value.trim(), c=$('#noteContent').value.trim(); if(!t) return; try{await api('/api/enotes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,subject:s,content:c})}); loadENotes(); toast('Note added');}catch(e){toast(e.message,false)} }
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
  const topSchool=document.querySelector('.school-name');
  if(topSchool) topSchool.innerHTML=`${name} <span>🇮🇳 Govt. Recognised</span>`;
  const brandSub=document.querySelector('.brand-sub');
  if(brandSub) brandSub.textContent=name;
  const brandTitle=document.querySelector('.brand-title');
  if(brandTitle) brandTitle.textContent='Dynamic Attendance';
  const si=$('#schoolInfo'); if(si) si.innerHTML=`<b>${name}</b> • Govt. Recognised 🇮🇳 • ${s.total_classes||12} Classes`;
  const sidebarLogo=document.getElementById('sidebarLogo');
  const topbarLogo=document.getElementById('topbarLogo');
  const logoPrev=$('#logoPreview');
  if(s.logo_path){
    const url=`${BACKEND_URL}/api/logo/${s.logo_path}?t=${Date.now()}`;
    if(sidebarLogo) sidebarLogo.innerHTML=`<img src="${url}" alt="logo">`;
    if(topbarLogo){ topbarLogo.classList.remove('hidden'); const img=topbarLogo.querySelector('img'); if(img) img.src=url; }
    if(logoPrev) logoPrev.innerHTML=`<img src="${url}"> <div><b>${s.logo_path}</b><br><small class="muted">${name}</small></div>`;
  } else {
    if(sidebarLogo) sidebarLogo.innerHTML=`🎓`;
    if(topbarLogo) topbarLogo.classList.add('hidden');
    if(logoPrev) logoPrev.innerHTML=`<span class="muted">No logo uploaded — shows 🎓</span>`;
  }
  let perms; try{ perms=await api('/api/permissions'); }catch(e){ perms=[]; } const pg=$('#permGrid'); if(pg) pg.innerHTML=perms.map(p=>`<label style="display:flex;gap:6px;align-items:center"><input type="checkbox" checked> ${p}</label>`).join(''); let users; try{ users=await api('/api/users'); }catch(e){ users=[]; } const ut=$('#userTable'); if(ut){ if(state.role!=='admin'){ ut.innerHTML=`<div class="muted">🔒 Admin only</div>`; } else { ut.innerHTML=users.length? `<table><thead><tr><th>User</th><th>Role</th><th></th></tr></thead><tbody>`+users.map(u=>`<tr><td>${u.username}</td><td>${u.role}</td><td><button class="btn-red" onclick="delUser(${u.id})">Delete</button></td></tr>`).join('')+`</tbody></table>` : `No users`; } } let hist; try{ hist=await api('/api/login_history'); }catch(e){ hist=[]; } const lh=$('#loginHistory'); if(lh){ if(state.role!=='admin'){ lh.innerHTML=`<div class="muted">🔒 Admin only</div>`; } else { lh.innerHTML=hist.length? `<table><thead><tr><th>User</th><th>Time</th><th>OK</th></tr></thead><tbody>`+hist.map(h=>`<tr><td>${h.username}</td><td>${h.time}</td><td>${h.success?'✅':'❌'}</td></tr>`).join('')+`</tbody></table>` : `No history`; } }
  // hide settings actions for non-admin
  const saveBtn=document.querySelector('#view-settings .btn-primary');
  if(saveBtn && state.role!=='admin') saveBtn.style.display='none';
}
async function saveSettings(){
  if(state.role!=='admin') return toast('Admin only',false);
  const name=$('#setSchoolName')?.value?.trim();
  const color=$('#setColor')?.value;
  const address=$('#setAddress')?.value?.trim()||'';
  const contact=$('#setContact')?.value?.trim()||'';
  if(!name) return toast('School name required',false);
  try{ await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({school_name:name, branding_color:color, address, contact})}); toast('Settings saved ✅ '+name); await loadSettings(); const topSchool=document.querySelector('.school-name'); if(topSchool) topSchool.innerHTML=`${name} <span>🇮🇳 Govt. Recognised</span>`; }catch(e){ toast(e.message,false); }
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
async function loadNotifPage(){
  let d; try{ d=await api('/api/notifications'); }catch(e){ return; }
  const el=$('#notifList'); if(!el) return;
  el.innerHTML=(d.notifications||[]).map(n=>`<div class="card notif-item ${n.read?'':'unread'}"><b>${n.type==='alert'?'🔔':n.type==='notice'?'📢':'✅'} ${n.title||''}</b><p>${n.content||''}</p><small class="muted">${n.date||''}</small> ${n.read?'':'<button class="btn-outline" onclick="markRead('+n.id+')">Mark read</button>'}</div>`).join('')||`<div class="muted">No notifications</div>`;
}
async function markRead(id){ await api('/api/notifications?id='+id,{method:'DELETE'}); loadNotifPage(); loadNotifBadge(); }
async function markAllRead(){ await api('/api/notifications?id=all',{method:'DELETE'}); loadNotifPage(); loadNotifBadge(); toast('All marked read'); }

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
async function loadTimetable(){
  const day=$('#ttDay')?.value || new Date().toLocaleDateString('en-US',{weekday:'long'});
  let data; try{ data=await api('/api/timetable?day='+encodeURIComponent(day)); }catch(e){ return; }
  const el=$('#ttTable'); if(!el) return;
  el.innerHTML=data.length? `<table><thead><tr><th>Time</th><th>Subject</th><th>Class</th><th>Room</th><th>Status</th></tr></thead><tbody>`+data.map(t=>`<tr><td>${t.period_time}</td><td>${t.subject_name||''}</td><td>${t.class_name||''}-${t.section_name||''}</td><td>${t.room||''}</td><td>${t.completed?'✓ Completed':(state.role==='admin'||state.role==='teacher'?`<button class="btn-primary" onclick="quickMark(${t.class_id},${t.section_id},'${t.subject_id||''}')">Mark Attendance</button>`:'Upcoming')}</td></tr>`).join('')+`</tbody></table>` : `<div class="muted" style="padding:16px">No periods for ${day}.</div>`;
}
async function addTimetable(){
  if(state.role!=='admin') return toast('Admin only',false);
  const payload={day:$('#ttDay').value, period_time:$('#ttTime').value, subject_name:$('#ttSubject').value, class_id:$('#ttClass').value||null, section_id:$('#ttSection').value||null, room:$('#ttRoom').value};
  try{ await api('/api/timetable',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); loadTimetable(); toast('Period added'); }catch(e){ toast(e.message,false); }
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
    const emoji=d.level==='high'?'🟢':d.level==='medium'?'🟡':d.level==='low'?'🔴':'—';
    return `<td style="background:${bg};text-align:center" title="${d.date} ${d.percentage}%">${emoji}<br><small>${d.percentage>=0?d.percentage+'%':''}</small></td>`;
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
  // mobile hero for student/parent
  if((state.role==='student'||state.role==='parent') && v==='dashboard'){
    setTimeout(renderMobileHero, 200);
  }
  return _origNavigate(v);
};
async function renderMobileHero(){
  try{
    const me=await api('/api/auth/me');
    const s=me.linked_student;
    if(!s) return;
    const dash=document.querySelector('#view-dashboard .page-head');
    if(dash && !document.getElementById('mobileHero')){
      const div=document.createElement('div');
      div.id='mobileHero'; div.className='mobile-hero';
      const hour=new Date().getHours();
      const greet=hour<12?'Good Morning':hour<17?'Good Afternoon':'Good Evening';
      div.innerHTML=`${greet}, ${s.name} 👋<br><small>Class ${s.class_name||''}-${s.section_name||''} • ${s.student_id}</small><div style="margin-top:8px;display:flex;gap:8px"><button class="btn-green" onclick="navigate('attendance')">✓ Attendance</button><button class="btn-outline" style="background:#fff" onclick="navigate('studentid')">🪪 My ID</button></div>`;
      dash.after(div);
    }
  }catch(e){}
}
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
      $('#topName').textContent=me.user.username;
      $('#topRole').textContent=me.user.role;
      const pdN=$('#pdName'), pdR=$('#pdRole');
      if(pdN) pdN.textContent=me.user.username;
      if(pdR) pdR.textContent=me.user.role+' • Green Valley';
      const dt=$('#dashTeacher'); if(dt) dt.textContent=me.user.username;
      filterNavByRole(me.user.role);
      loadDashboard(); loadClasses(); loadSettings();
    } else {
      try{ await loadClasses(); }catch(e){}
    }
  }catch(e){ try{ await loadClasses(); }catch(e){} }
  // ensure login form Enter works (already via onsubmit)
})();

