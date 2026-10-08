/* =====================================================================
   Student & Parent portal
   - two dedicated login screens (?login=student | ?login=parent)
   - student dashboard, parent dashboard with child switching
   - all data comes from /api/portal/* which enforces ownership server-side
   ===================================================================== */
const q  = s => document.querySelector(s);
const qa = s => [...document.querySelectorAll(s)];
const be = () => (typeof BACKEND_URL !== 'undefined') ? BACKEND_URL : '';

const portal = {
  mode: 'staff',      // staff | student | parent
  me: null,           // /api/auth/me payload
  children: [],       // linked students (1 for a student, 1..n for a parent)
  childPk: null,      // currently selected child (parents only)
  overview: null,
  marks: null,
  attMonth: null      // YYYY-MM shown on the attendance calendar
};

function esc(v){
  if (v === null || v === undefined) return '';
  return String(v).replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* ---------------- login screens ---------------- */
const LOGIN_CARDS = {
  staff:   '#loginForm',
  student: '#studentLoginForm',
  parent:  '#parentLoginForm'
};

function showLoginCard(mode){
  if (!LOGIN_CARDS[mode]) mode = 'staff';
  portal.mode = mode;
  Object.keys(LOGIN_CARDS).forEach(k => {
    const el = q(LOGIN_CARDS[k]);
    if (el) el.classList.toggle('hidden', k !== mode);
  });
  try {
    const url = mode === 'staff' ? location.pathname : location.pathname + '?login=' + mode;
    history.replaceState(null, '', url);
  } catch (e) {}
  restoreRemember();
  const focus = { staff: '#loginUser', student: '#stIdent', parent: '#parIdent' }[mode];
  const f = q(focus);
  if (f) setTimeout(() => f.focus(), 60);
}

function restoreRemember(){
  const val = localStorage.getItem('portal.remember.' + portal.mode) || '';
  if (portal.mode === 'student'){
    const i = q('#stIdent'); if (i && !i.value) i.value = val;
    const r = q('#stRemember'); if (r) r.checked = !!val;
  } else if (portal.mode === 'parent'){
    const i = q('#parIdent'); if (i && !i.value) i.value = val;
    const r = q('#parRemember'); if (r) r.checked = !!val;
  } else if (portal.mode === 'staff'){
    const i = q('#loginUser'); if (i && !val && i.value === '') i.value = 'admin';
    if (i && val) i.value = val;
    const r = q('#rememberMe'); if (r) r.checked = !!val;
  }
}

function rememberIdentity(mode, value){
  const key = 'portal.remember.' + mode;
  if (value) localStorage.setItem(key, value); else localStorage.removeItem(key);
}

function toggleField(id){
  const i = document.getElementById(id);
  if (i) i.type = (i.type === 'password') ? 'text' : 'password';
}
function toggleStPwd(){ toggleField('stPass'); }
function toggleParPwd(){ toggleField('parPass'); }

function forgotPassword(mode){
  const who = mode === 'student' ? 'your class teacher' : 'the school office';
  const t = (typeof toast === 'function') ? toast : (m => alert(m));
  t('Please contact ' + who + ' to reset your ' +
    (mode === 'parent' ? 'Parent ID password / PIN.' : 'password.'));
}

function loginError(sel, message){
  const el = q(sel);
  if (el) el.textContent = message || '';
}

function setBusy(btnSel, busy, busyText, idleText){
  const b = q(btnSel);
  if (!b) return;
  b.disabled = busy;
  b.textContent = busy ? busyText : idleText;
}

async function portalLogin(endpoint, body, btnSel, msgSel, rememberKey, mode){
  loginError(msgSel, '');
  if (!body.identifier || !body.password){
    loginError(msgSel, mode === 'student'
      ? 'Student ID and password are required'
      : 'Parent ID / mobile number and password are required');
    return;
  }
  setBusy(btnSel, true, 'Signing in...', 'Login →');
  try {
    const r = await fetch(be() + endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify(body)
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok){
      const e = j.error;
      loginError(msgSel, (e && e.message) || (typeof e === 'string' ? e : 'Login failed'));
      return;
    }
    rememberIdentity(rememberKey, body.remember ? body.identifier : '');
    await enterPortal(j, mode);
  } catch (err){
    loginError(msgSel, 'Could not reach the server. Please try again.');
  } finally {
    setBusy(btnSel, false, 'Signing in...', 'Login →');
  }
}

function doStudentLogin(e){
  if (e) e.preventDefault();
  portalLogin('/api/auth/student-login',
    { identifier: (q('#stIdent').value || '').trim(),
      password: q('#stPass').value,
      remember: q('#stRemember') && q('#stRemember').checked },
    '#stLoginBtn', '#stLoginMsg', 'student', 'student');
}

function doParentLogin(e){
  if (e) e.preventDefault();
  portalLogin('/api/auth/parent-login',
    { identifier: (q('#parIdent').value || '').trim(),
      password: q('#parPass').value,
      remember: q('#parRemember') && q('#parRemember').checked },
    '#parLoginBtn', '#parLoginMsg', 'parent', 'parent');
}

/* ---------------- entering / leaving the app ---------------- */
async function enterPortal(j, mode){
  state.currentUser = j.user;
  state.role = j.user.role;
  portal.mode = mode || j.user.role;
  const ls = q('#loginScreen'); if (ls) ls.style.display = 'none';
  const sh = q('#appShell');    if (sh) sh.classList.remove('hidden');
  if (typeof filterNavByRole === 'function') filterNavByRole(state.role);
  await loadPortalMe();
  const name = portalAccountName();
  paintTopbar(name, state.role);
  if (typeof loadClasses === 'function') { try { await loadClasses(); } catch(e){} }
  if (typeof loadSettings === 'function'){ try { await loadSettings(); } catch(e){} }
  navigate('dashboard');
  if (typeof toast === 'function') toast('Welcome ' + name + ' (' + state.role + ')');
}

function paintTopbar(name, role){
  const set = (sel, val) => { const el = q(sel); if (el && val) el.textContent = val; };
  set('#topName', name);
  set('#topRole', role);
  set('#pdName', name);
  set('#pdRole', role + ' • ' + (q('#topSchoolName') ? q('#topSchoolName').textContent : 'School'));
  set('#dashTeacher', name);
  set('#roleBadge', role.charAt(0).toUpperCase() + role.slice(1));
  const av = q('#topAvatar');
  const photo = activeChild() && activeChild().photo;
  if (av) av.src = photo ? (be() + '/api/photos/' + photo) : 'https://i.pravatar.cc/100?img=5';
}

async function loadPortalMe(){
  const j = await api('/api/auth/me');
  portal.me = j || {};
  portal.children = (j && j.children) || [];
  if (portal.children.length){
    const remembered = parseInt(localStorage.getItem('portal.child.' + (state.currentUser ? state.currentUser.id : 0)) || '0', 10);
    const hit = portal.children.find(c => c.id === remembered);
    if (portal.childPk === null || !portal.children.find(c => c.id === portal.childPk)){
      portal.childPk = (hit || portal.children[0]).id;
    }
  } else {
    portal.childPk = null;
  }
  return portal.me;
}

function activeChild(){
  if (!portal.children.length) return null;
  return portal.children.find(c => c.id === portal.childPk) || portal.children[0];
}
function activeChildName(){
  const c = activeChild();
  return c ? c.name : null;
}

/* Who appears in the top bar: the parent themselves for a parent session,
   otherwise the student whose record is open. */
function portalAccountName(){
  if (state.role === 'parent' && portal.me && portal.me.parent && portal.me.parent.name)
    return portal.me.parent.name;
  const c = activeChild();
  if (c) return c.name;
  if (portal.me && portal.me.student && portal.me.student.name)
    return portal.me.student.name;
  return state.currentUser ? state.currentUser.username : '';
}
function childQs(){
  const c = activeChild();
  return c ? ('&student_pk=' + c.id) : '';
}

function switchChild(pk){
  portal.childPk = pk;
  localStorage.setItem('portal.child.' + (state.currentUser ? state.currentUser.id : 0), String(pk));
  const c = activeChild();
  paintTopbar(portalAccountName(), state.role);
  const v = qa('.view.active').map(s => s.id.replace('view-', ''))[0] || 'dashboard';
  if (typeof toast === 'function') toast('Showing ' + (c ? c.name : '') + "'s record");
  navigate(v);
}

function logoutPortal(){
  portal.me = null; portal.children = []; portal.childPk = null;
  portal.overview = null; portal.marks = null; portal.attMonth = null;
}

/* ---------------- shared rendering helpers ---------------- */
const DOW = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
const STATUS_LABEL = { P:'Present', A:'Absent', L:'Leave', T:'Late', H:'Holiday' };
const STATUS_CLASS = { P:'p', A:'a', L:'l', T:'t', H:'h' };

function calendarGrid(days){
  if (!days || !days.length) return '<p class="muted">No data for this month.</p>';
  const firstDow = days[0].dow;                 // 0 = Monday
  let out = '<div class="cal-head">' + DOW.map(d => '<span>' + d + '</span>').join('') + '</div><div class="cal-body">';
  for (let i = 0; i < firstDow; i++) out += '<span class="cal-cell empty"></span>';
  days.forEach(d => {
    const st = d.status || 'n';
    const cls = STATUS_CLASS[st] || 'n';
    const label = STATUS_LABEL[st] || 'Not marked';
    const day = String(parseInt(d.date.slice(8, 10), 10));
    const title = d.date + ' — ' + label + (d.reason ? ' (' + d.reason + ')' : '');
    out += '<span class="cal-cell ' + cls + '" title="' + esc(title) + '">' +
           '<b>' + day + '</b><i>' + esc(label) + '</i></span>';
  });
  out += '</div>';
  return out;
}

function stat(label, value, icon, cls){
  return '<div class="stat-card ' + (cls || 'blue') + '"><div class="stat-icon">' + (icon || '📊') + '</div>' +
         '<div><small>' + esc(label) + '</small><b>' + esc(value) + '</b></div></div>';
}

function childSwitcher(){
  if (!portal.children || portal.children.length < 2) return '';
  return '<div class="child-switch" role="tablist" aria-label="Select child">' +
    portal.children.map(c =>
      '<button role="tab" aria-selected="' + (c.id === portal.childPk) + '" class="chip' +
      (c.id === portal.childPk ? ' active' : '') + '" onclick="switchChild(' + c.id + ')">' +
      esc(c.name) + ' <small>' + esc(c.class_name || '') + '-' + esc(c.section_name || '') + '</small></button>'
    ).join('') + '</div>';
}

function profileCard(s){
  if (!s) return '';
  const photo = s.photo ? (be() + '/api/photos/' + s.photo) : '';
  const row = (k, v) => '<div class="pf-row"><span>' + esc(k) + '</span><b>' + esc(v || '—') + '</b></div>';
  return '<div class="card pf-card">' +
    '<div class="pf-top">' +
      (photo ? '<img class="pf-photo" src="' + photo + '" alt="Photo of ' + esc(s.name) + '">'
             : '<div class="pf-photo placeholder" aria-hidden="true">🎓</div>') +
      '<div><h3>' + esc(s.name) + '</h3>' +
      '<p class="muted">' + esc(s.class_name || '') + ' — ' + esc(s.section_name || '') +
      ' • Roll ' + esc(s.roll_no || '—') + '</p>' +
      '<span class="pill">' + esc(s.student_id || '') + '</span></div>' +
    '</div>' +
    '<div class="pf-rows">' +
      row('Student ID', s.student_id) +
      row('Admission No.', s.admission_no) +
      row('Class', s.class_name) +
      row('Section', s.section_name) +
      row('Roll No.', s.roll_no) +
      row('Date of Birth', s.dob) +
      row("Father's Name", s.father_name) +
      row("Mother's Name", s.mother_name) +
      row('Phone', s.phone) +
      row('Address', s.address) +
    '</div>' +
    '<div class="pf-actions">' +
      '<button class="btn-outline" onclick="navigate(\'profile\')">⚙️ Profile Settings</button>' +
      '<button class="btn-outline" onclick="navigate(\'password\')">🔑 Change Password</button>' +
      '<button class="btn-ghost" onclick="logout()">↪ Logout</button>' +
    '</div></div>';
}

function homeworkItem(h){
  const cls = h.status === 'Overdue' ? 'danger' : (h.status === 'Due soon' ? 'warn' : 'ok');
  return '<div class="card hw-card ' + cls + '">' +
    '<div class="hw-head"><b>' + esc(h.title) + '</b>' +
    '<span class="pill ' + cls + '">' + esc(h.status || '') + '</span></div>' +
    (h.subject ? '<small class="muted">' + esc(h.subject) + '</small>' : '') +
    (h.description ? '<p>' + esc(h.description) + '</p>' : '') +
    '<div class="hw-foot"><span>📅 ' + esc(h.due_date || 'No due date') + '</span></div></div>';
}

function noticeItem(n){
  return '<div class="card notice-card"><b>' + esc(n.title) + '</b>' +
    '<p class="muted">' + esc(n.content) + '</p>' +
    '<small class="muted">' + esc(n.date) + '</small></div>';
}

/* ---------------- student / parent HOME ---------------- */
async function loadPortalHome(){
  const host = q('#portalHome');
  if (!host) return;
  const dash = q('#view-dashboard');
  if (dash) dash.classList.add('portal-mode');
  host.classList.remove('hidden');
  host.innerHTML = '<div class="card">Loading your dashboard…</div>';
  try {
    if (!portal.me) await loadPortalMe();
    const [ov, mk, hwData] = await Promise.all([
      api('/api/portal/overview?month=' + monthKey() + childQs()),
      api('/api/portal/marks?' + childQs().slice(1)),
      api('/api/portal/homework' + (childQs() ? '?' + childQs().slice(1) : ''))
        .catch(() => ({ homework: [] }))
    ]);
    portal.overview = ov;
    portal.marks = mk;
    portal._hwCache = { pk: portal.childPk, rows: hwData.homework || [] };
    host.innerHTML = renderPortalHome(ov, mk);
  } catch (e){
    host.innerHTML = '<div class="card"><b>We could not load your dashboard</b>' +
      '<p class="muted">' + esc(e.message) + '</p>' +
      '<button class="btn-outline" onclick="loadPortalHome()">⟳ Try again</button></div>';
  }
}

function monthKey(d){
  const t = d || new Date();
  return t.getFullYear() + '-' + String(t.getMonth() + 1).padStart(2, '0');
}

function renderPortalHome(ov, mk){
  const st = ov.stats || {};
  const s  = ov.student || {};
  const isParent = state.role === 'parent';
  const latest = (mk && mk.exams && mk.exams.length) ? mk.exams[mk.exams.length - 1] : null;
  const hw = ov.homework || {};
  const notices = ov.notices || [];
  const upcoming = ov.upcoming_exams || [];

  let out = childSwitcher();

  out += '<div class="page-head"><div><h2>' +
    (isParent ? 'Parent Dashboard' : 'Student Dashboard') + '</h2>' +
    '<p class="muted">' + esc(s.name || '') + ' • ' + esc(s.class_name || '') + '-' +
    esc(s.section_name || '') + ' • Session 2026–27</p></div>' +
    '<div class="page-actions">' +
    '<button class="btn-outline" onclick="loadPortalHome()">⟳ Refresh</button>' +
    '<span class="badge-date">' + esc(new Date().toLocaleDateString('en-IN',
      {weekday:'short', day:'2-digit', month:'short', year:'numeric'})) + '</span></div></div>';

  out += '<div class="stat-grid">' +
    stat('Attendance', (st.percentage !== undefined ? st.percentage : 0) + '%', '📊', 'blue') +
    stat('Today', ov.today ? STATUS_LABEL[ov.today] : 'Not marked', '🕐', ov.today === 'A' ? 'red' : 'green') +
    stat('Present', st.present || 0, '✅', 'green') +
    stat('Absent', st.absent || 0, '❌', 'red') +
    stat('Leave', st.leave || 0, '🟡', 'yellow') +
    stat('Homework Due', hw.due_soon || 0, '📝', 'blue') +
    '</div>';

  out += '<div class="grid-2" style="margin-top:12px">';

  /* --- attendance calendar --- */
  out += '<div class="card"><div class="card-head"><h3>📅 Attendance — ' + esc(ov.month || '') + '</h3>' +
    '<button class="btn-outline" onclick="navigate(\'attcal\')">Full calendar</button></div>' +
    calendarGrid(ov.calendar) +
    '<div class="att-legend">' +
      '<span><i class="sw p"></i> Present</span><span><i class="sw a"></i> Absent</span>' +
      '<span><i class="sw l"></i> Leave</span><span><i class="sw t"></i> Late</span>' +
      '<span><i class="sw h"></i> Holiday</span><span><i class="sw n"></i> Not marked</span>' +
    '</div>' +
    '<p class="muted sm">Working days: <b>' + (st.working || 0) + '</b> • Late: <b>' + (st.late || 0) + '</b></p></div>';

  /* --- homework --- */
  out += '<div class="card"><div class="card-head"><h3>📝 Homework</h3>' +
    '<button class="btn-outline" onclick="navigate(\'homework\')">View all</button></div>';
  const hwRows = (portal._hwCache && portal._hwCache.pk === portal.childPk)
    ? (portal._hwCache.rows || []) : [];
  out += hwRows.length
    ? hwRows.slice(0, 4).map(homeworkItem).join('')
    : '<p class="muted">No homework has been assigned yet.</p>';
  out += '</div>';

  out += '</div>'; // grid-2

  out += '<div class="grid-2" style="margin-top:12px">';

  /* --- exam report summary --- */
  out += '<div class="card"><div class="card-head"><h3>📊 Exam Report</h3>' +
    '<button class="btn-outline" onclick="navigate(\'exams\')">View marks</button></div>';
  if (latest){
    out += '<div class="exam-mini"><b>' + esc(latest.exam_type) + '</b>' +
      '<span class="grade-badge">' + esc(latest.grade) + '</span>' +
      '<p class="muted">' + latest.obtained + ' / ' + latest.max_marks +
      ' • ' + latest.percentage + '%</p></div>';
    out += '<div class="table-wrap"><table><thead><tr><th>Subject</th><th>Marks</th><th>%</th><th>Grade</th></tr></thead><tbody>' +
      latest.subjects.map(r => '<tr><td>' + esc(r.subject_name) + '</td><td>' +
        (r.obtained == null ? '—' : r.obtained + '/' + r.max_marks) + '</td><td>' +
        (r.percentage == null ? '—' : r.percentage + '%') + '</td><td>' + esc(r.grade) + '</td></tr>').join('') +
      '</tbody></table></div>';
  } else {
    out += '<p class="muted">No marks published yet.</p>';
  }
  out += '</div>';

  /* --- profile --- */
  out += profileCard(s);

  out += '</div>';

  /* --- notices + date sheet --- */
  out += '<div class="grid-2" style="margin-top:12px">';
  out += '<div class="card"><div class="card-head"><h3>📢 School Notices</h3>' +
    '<button class="btn-outline" onclick="navigate(\'notices\')">All notices</button></div>' +
    (notices.length ? notices.slice(0, 3).map(noticeItem).join('')
                    : '<p class="muted">No notices yet.</p>') + '</div>';
  out += '<div class="card"><div class="card-head"><h3>📋 Upcoming Exams</h3>' +
    '<button class="btn-outline" onclick="navigate(\'datesheet\')">Date sheet</button></div>' +
    (upcoming.length
      ? '<div class="table-wrap"><table><thead><tr><th>Exam</th><th>Subject</th><th>Date</th><th>Time</th></tr></thead><tbody>' +
        upcoming.map(d => '<tr><td>' + esc(d.exam_type) + '</td><td>' + esc(d.subject) + '</td><td>' +
          esc(d.date) + '</td><td>' + esc(d.time) + '</td></tr>').join('') + '</tbody></table></div>'
      : '<p class="muted">No date sheet published yet.</p>') + '</div>';
  out += '</div>';

  return out;
}

/* ---------------- attendance calendar view ---------------- */
function shiftAttCal(delta){
  const parts = (portal.attMonth || monthKey()).split('-').map(Number);
  const d = new Date(parts[0], parts[1] - 1 + delta, 1);
  portal.attMonth = monthKey(d);
  loadAttCal();
}

async function loadAttCal(){
  const statsEl = q('#attCalStats'), gridEl = q('#attCalGrid'),
        listEl = q('#attCalList'), monthEl = q('#attCalMonth'), subEl = q('#attCalSub');
  if (!gridEl) return;
  if (!portal.attMonth) portal.attMonth = monthKey();
  try {
    if (!portal.me) await loadPortalMe();
    const data = await api('/api/portal/attendance?month=' + portal.attMonth + childQs());
    const st = data.stats || {};
    if (monthEl) monthEl.textContent = data.month;
    if (subEl) subEl.textContent = (activeChildName() || (portal.me.student && portal.me.student.name) || '') +
      ' • ' + (st.working || 0) + ' working days';
    if (statsEl) statsEl.innerHTML =
      stat('This month', (st.percentage || 0) + '%', '📊', 'blue') +
      stat('Present', st.present || 0, '✅', 'green') +
      stat('Absent', st.absent || 0, '❌', 'red') +
      stat('Leave', st.leave || 0, '🟡', 'yellow') +
      stat('Late', st.late || 0, '🕔', 'blue');
    gridEl.innerHTML = calendarGrid(data.calendar);
    if (listEl){
      const rows = (data.history || []).slice(0, 20);
      listEl.innerHTML = rows.length
        ? '<table><thead><tr><th>Date</th><th>Status</th><th>Time</th><th>Remark</th></tr></thead><tbody>' +
          rows.map(r => '<tr><td>' + esc(r.date) + '</td><td>' +
            '<span class="pill ' + (STATUS_CLASS[r.status] || 'n') + '">' +
            esc(STATUS_LABEL[r.status] || r.status) + '</span></td><td>' + esc(r.time || '—') +
            '</td><td>' + esc(r.leave_reason || '—') + '</td></tr>').join('') +
          '</tbody></table>'
        : '<p class="muted">No attendance recorded yet.</p>';
    }
  } catch (e){
    gridEl.innerHTML = '<p class="muted">' + esc(e.message) + '</p>';
  }
}

/* ---------------- homework view ---------------- */
async function loadHomeworkView(){
  const list = q('#homeworkList'), statsEl = q('#hwStats'), sub = q('#hwSub');
  if (!list) return;
  list.innerHTML = '<div class="card">Loading homework…</div>';
  try {
    if (!portal.me) await loadPortalMe();
    const data = await api('/api/portal/homework' + (childQs() ? '?' + childQs().slice(1) : ''));
    const rows = data.homework || [];
    portal._hwCache = { pk: portal.childPk, rows };
    if (sub) sub.textContent = (data.class || '') + '-' + (data.section || '') +
      ' • ' + rows.length + ' assignment' + (rows.length === 1 ? '' : 's');
    const due = rows.filter(r => r.status === 'Due soon' || r.status === 'Overdue').length;
    const over = rows.filter(r => r.status === 'Overdue').length;
    if (statsEl) statsEl.innerHTML =
      stat('Total', rows.length, '📝', 'blue') +
      stat('Due soon', due, '⏰', 'yellow') +
      stat('Overdue', over, '⚠️', 'red');
    list.innerHTML = rows.length
      ? rows.map(homeworkItem).join('')
      : '<div class="card"><p class="muted">No homework has been assigned yet.</p></div>';
  } catch (e){
    list.innerHTML = '<div class="card"><p class="muted">' + esc(e.message) + '</p></div>';
  }
}

/* ---------------- exam report view ---------------- */
async function loadExamReport(){
  const overall = q('#examOverall'), list = q('#examList'), sub = q('#examSub');
  if (!list) return;
  list.innerHTML = '<div class="card">Loading exam report…</div>';
  try {
    if (!portal.me) await loadPortalMe();
    const data = await api('/api/portal/marks' + (childQs() ? '?' + childQs().slice(1) : ''));
    portal.marks = data;
    const exams = data.exams || [];
    const ov = data.overall || {};
    if (sub) sub.textContent = (activeChildName() || '') + ' • ' + exams.length + ' exam(s) recorded';
    if (overall) overall.innerHTML =
      stat('Overall %', (ov.percentage == null ? '—' : ov.percentage + '%'), '📊', 'blue') +
      stat('Overall Grade', (ov.grade || '—'), '🏅', 'green') +
      stat('Total Score', (ov.max_marks ? ov.obtained + '/' + ov.max_marks : '—'), '✅', 'green') +
      stat('Exams', exams.length, '📋', 'blue');
    list.innerHTML = exams.length ? exams.map(ex =>
      '<div class="card"><div class="card-head"><h3>' + esc(ex.exam_type) + '</h3>' +
      '<span class="grade-badge">' + esc(ex.grade) + '</span></div>' +
      '<div class="table-wrap"><table><thead><tr><th>Subject</th><th>Max</th><th>Obtained</th><th>%</th><th>Grade</th></tr></thead><tbody>' +
      ex.subjects.map(r => '<tr><td>' + esc(r.subject_name) + '</td><td>' + esc(r.max_marks) +
        '</td><td>' + esc(r.obtained) + '</td><td>' + esc(r.percentage) + '</td><td>' +
        esc(r.grade) + '</td></tr>').join('') +
      '</tbody></table></div>' +
      '<p class="muted sm">Total: <b>' + ex.obtained + '/' + ex.max_marks + '</b> • ' +
      ex.percentage + '%</p></div>').join('')
      : '<div class="card"><p class="muted">No marks have been published for this student yet.</p></div>';
  } catch (e){
    list.innerHTML = '<div class="card"><p class="muted">' + esc(e.message) + '</p></div>';
  }
}

/* ---------------- profile view ---------------- */
async function loadProfileView(){
  const host = q('#profileCard');
  if (!host) return;
  host.innerHTML = '<div class="card">Loading profile…</div>';
  try {
    if (!portal.me) await loadPortalMe();
    const isStaff = ['admin', 'teacher'].includes(state.role);
    if (isStaff){
      const u = state.currentUser;
      host.innerHTML =
        '<div class="card"><h3>👤 Account</h3>' +
        '<div class="pf-rows">' +
        '<div class="pf-row"><span>Username</span><b>' + esc(u.username) + '</b></div>' +
        '<div class="pf-row"><span>Role</span><b>' + esc(u.role) + '</b></div>' +
        '<div class="pf-row"><span>User ID</span><b>' + esc(u.id) + '</b></div>' +
        '</div><div class="pf-actions">' +
        '<button class="btn-outline" onclick="navigate(\'password\')">🔑 Change Password</button>' +
        '<button class="btn-ghost" onclick="logout()">↪ Logout</button></div></div>' +
        '<div class="card"><h3>🏫 School</h3><div class="pf-rows">' +
        '<div class="pf-row"><span>Session</span><b>2026–27</b></div>' +
        '<div class="pf-row"><span>Support</span><b>Contact the admin</b></div></div></div>';
      return;
    }
    const data = await api('/api/portal/profile' + (childQs() ? '?' + childQs().slice(1) : ''));
    const sch = data.school || {};
    const guardians = data.guardians || [];
    host.innerHTML =
      '<div style="grid-column:1/-1">' + childSwitcher() + '</div>' +
      profileCard(data.student) +
      '<div class="card"><h3>👨‍👩‍👧 Guardians</h3><div class="pf-rows">' +
      (guardians.length ? guardians.map(g =>
        '<div class="pf-row"><span>' + esc(g.parent_id || 'Parent') + '</span><b>' +
        esc(g.name) + (g.phone ? ' • ' + esc(g.phone) : '') + '</b></div>').join('')
        : '<p class="muted">No guardian record on file.</p>') +
      '</div><h4 style="margin-top:14px">🏫 School contact</h4><div class="pf-rows">' +
      '<div class="pf-row"><span>School</span><b>' + esc(sch.school_name) + '</b></div>' +
      '<div class="pf-row"><span>Address</span><b>' + esc(sch.address || '—') + '</b></div>' +
      '<div class="pf-row"><span>Contact</span><b>' + esc(sch.contact || '—') + '</b></div>' +
      '</div></div>';
  } catch (e){
    host.innerHTML = '<div class="card"><p class="muted">' + esc(e.message) + '</p></div>';
  }
}

/* ---------------- change password ---------------- */
function loadPasswordView(){
  const m = q('#pwMsg');
  if (m) m.textContent = '';
  ['curPw', 'newPw', 'confPw'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
}

async function changePassword(){
  const msg = q('#pwMsg');
  const cur = q('#curPw').value, nw = q('#newPw').value, cf = q('#confPw').value;
  const say = (t, ok) => { if (msg){ msg.textContent = t; msg.style.color = ok ? 'var(--green,#16a34a)' : ''; } };
  if (!cur || !nw || !cf) return say('All three fields are required.', false);
  if (nw.length < 6) return say('New password must be at least 6 characters.', false);
  if (nw !== cf) return say('New passwords do not match.', false);
  try {
    const r = await fetch(be() + '/api/auth/change-password', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify({ current_password: cur, new_password: nw })
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return say((j && j.error) || 'Could not update password.', false);
    say('Password updated successfully.', true);
    ['curPw', 'newPw', 'confPw'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    if (typeof toast === 'function') toast('Password changed');
  } catch (e){
    say('Could not reach the server.', false);
  }
}
