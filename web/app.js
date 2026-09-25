let state = { me: null, people: [], projects: [], applications: [], csrfToken: "" };
let searchQuery = "";
let toastTimer;
let lastSnapshot = "";
let refreshGeneration = 0;
let messageGeneration = 0;
let lastMessages = "";
const discussionDrafts = new Map();
const leaveDrafts = new Map();
const app = document.querySelector("#app");

async function api(path, method = "GET", data = null) {
  const response = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": state.csrfToken },
    body: data === null ? undefined : JSON.stringify(data)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "操作失败，请重试。");
  return result;
}

async function refresh(force = false) {
  const generation = ++refreshGeneration;
  try {
    const next = await api("/state");
    if (generation !== refreshGeneration) return;
    const snapshot = JSON.stringify(next);
    if (snapshot === lastSnapshot && !force) return;
    state = next;
    lastSnapshot = snapshot;
    const [route, subpage] = location.hash.slice(1).split("/");
    const editing = document.activeElement?.closest("form") || ["create", "login", "register"].includes(route) || (route === "profile" && subpage === "edit");
    const lostDiscussionAccess = route === "discussion" && !state.projects.find(item => item.id === Number(subpage))?.members.includes(state.me?.id);
    if (force || lostDiscussionAccess || !editing) render();
  } catch (error) { showToast(`同步失败：${error.message}`); }
}

function person(id) { return state.people.find(item => item.id === Number(id)); }
function project(id) { return state.projects.find(item => item.id === Number(id)); }
function activePerson() { return state.me; }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}
function tags(items, limit = 4) { return (items || []).slice(0, limit).map(item => `<span class="tag">${escapeHtml(item)}</span>`).join(""); }
function avatar(user, variant = "") { return `<span class="avatar ${variant}">${escapeHtml(user.name.slice(0, 1))}</span>`; }
function ownerName(item) { return person(item.ownerId)?.name || "未知"; }
function memberCount(item) { return item.members.length; }
function match(_user, item) { return item.match; }

function showToast(message) {
  const node = document.querySelector("#toast");
  node.textContent = message;
  node.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("visible"), 3300);
}

function updateHeader(route) {
  document.querySelector("#account-controls").innerHTML = state.me
    ? `<span class="account-name">${escapeHtml(state.me.name)}</span><button class="text-action" type="button" data-action="logout">退出</button><a class="button button-dark header-create" href="#create">+ 发起项目</a>`
    : `<a class="text-action" href="#login">登录</a><a class="button button-dark" href="#register">创建账号</a>`;
  const active = route === "project" || route === "create" ? "projects" : route === "card" ? "people" : route;
  document.querySelectorAll("[data-nav]").forEach(link => link.classList.toggle("active", link.dataset.nav === active));
}

function projectStatus(item, user) {
  if (!user) return "";
  if (item.ownerId === user.id) return "我发起的";
  if (item.members.includes(user.id)) return "已加入";
  const application = state.applications.find(row => row.projectId === item.id && row.userId === user.id);
  if (application && application.status !== "left") return ({ pending: "已申请", accepted: "已加入", rejected: "申请已拒绝" })[application.status] || "已申请";
  if (memberCount(item) >= item.capacity) return "已满员";
  return "";
}

function projectCard(item, index, status = "") {
  const score = match(activePerson(), item);
  const full = memberCount(item) >= item.capacity;
  return `<article class="panel project-card">
    <div class="card-top"><span class="chip ${(status || full) ? "orange" : ""}">${escapeHtml(status || (full ? "已满员" : item.category))}</span><span class="card-index">NO. ${String(index + 1).padStart(2, "0")}</span></div>
    <h3><a href="#project/${item.id}">${escapeHtml(item.title)}</a></h3>
    <p>${escapeHtml(item.description)}</p>
    <div class="tag-row">${tags(item.needs)}</div>
    <div class="card-bottom"><div class="score-inline"><strong>${score ? score.total : "—"}</strong><span>匹配指数</span></div><a href="#project/${item.id}">查看项目 ↗</a></div>
  </article>`;
}

function renderProjects() {
  const current = activePerson();
  const sorted = [...state.projects].sort((a, b) => (match(current, b)?.total || 0) - (match(current, a)?.total || 0));
  const recommended = current ? sorted.filter(item => !projectStatus(item, current)) : sorted;
  const other = current ? sorted.filter(item => projectStatus(item, current)) : [];
  const openSpots = state.projects.reduce((total, item) => total + Math.max(item.capacity - memberCount(item), 0), 0);
  return `<section class="hero"><div class="hero-copy"><p class="hero-kicker">FIND YOUR PEOPLE · BUILD YOUR IDEA</p>
    <h1>下一队，<br><em>正在这里发生。</em></h1>
    <p>带上你的技能和好奇心，找到真正想一起动手的人。从一张名片、一个项目开始。</p>
    <div class="hero-actions"><a class="button button-lime" href="#people">认识伙伴 ↗</a><a class="button button-light" href="#create">发起我的项目</a></div></div>
    <div class="hero-art" aria-hidden="true"><div class="hero-orbit"></div><div class="art-card one"><small>PROFILE / 01</small><strong>介绍你的技能<br>和兴趣</strong><span>让队友更快认识你</span></div><div class="art-card two"><small>PROJECT / 02</small><strong>好点子<br>正在招募队友</strong><span>一起行动 ↗</span></div><span class="hero-spark">✳</span></div></section>
    <div class="stats"><div class="stat"><strong>${state.projects.length.toString().padStart(2, "0")}</strong><span>个现场项目</span></div><div class="stat"><strong>${state.people.length.toString().padStart(2, "0")}</strong><span>位潜在伙伴</span></div><div class="stat"><strong>${openSpots.toString().padStart(2, "0")}</strong><span>个开放名额</span></div></div>
    <div class="section-head"><div><p class="eyebrow">EXPLORE PROJECTS</p><h2>${current ? "推荐给你" : "浏览全部项目"}</h2><p>${current ? "这里是还可申请的项目，按你的匹配指数排序。" : "登录并完善名片后，可以看到专属匹配指数。"}</p></div><a href="#create">有自己的点子？发起项目 ↗</a></div>
    <div class="grid">${recommended.map((item, index) => projectCard(item, index)).join("") || `<p class="empty">${current ? "目前没有可申请的项目，可以看看下方的其他项目。" : "还没有项目，来发起第一个吧。"}</p>`}</div>
    ${other.length ? `<div class="section-head other-projects"><div><p class="eyebrow">OTHER PROJECTS</p><h2>其他项目</h2><p>已加入、已申请或已满员的项目仍可查看。</p></div></div><div class="grid">${other.map((item, index) => projectCard(item, index, projectStatus(item, current))).join("")}</div>` : ""}`;
}

function personCard(user, index) {
  const color = ["", "teal", "orange"][index % 3];
  return `<article class="panel person-card">${avatar(user, color)}<h3><a href="#card/${user.id}">${escapeHtml(user.name)}</a></h3>
    <span class="small-note">${escapeHtml(user.role)} · 每周 ${user.hours} 小时</span>
    <p>${escapeHtml(user.bio)}</p><div class="tag-row">${tags([...user.skills, ...user.interests], 4)}</div>
    <a href="#card/${user.id}">打开个人名片 ↗</a></article>`;
}

function renderPeople() {
  const query = searchQuery.trim().toLocaleLowerCase();
  const results = state.people.filter(user => user.skills.length && user.interests.length && [user.name, ...user.skills, ...user.interests].some(value => value.toLocaleLowerCase().includes(query)));
  return `<section class="page-intro"><p class="eyebrow">MEET THE MAKERS</p><h1>认识现场伙伴<span class="logo-dot">.</span></h1><p>一个技能、一份兴趣，就可能成为下一次合作的起点。</p></section>
    <form id="search-form" class="search-bar"><span aria-hidden="true">⌕</span><input name="query" value="${escapeHtml(searchQuery)}" placeholder="搜索昵称、技能或兴趣，例如 Python、教育" aria-label="搜索个人名片"><button class="button button-small" type="submit">搜索</button></form>
    <div class="result-line"><span>找到 ${results.length} 张名片</span><span>点击名片了解更多</span></div>
    <div class="grid">${results.map(personCard).join("") || `<p class="empty">没有找到相关名片，换个关键词试试。</p>`}</div>`;
}

function renderDiscussions() {
  if (!state.me) return renderAuth("login");
  const joined = state.projects.filter(item => item.members.includes(state.me.id));
  return `<section class="page-intro"><p class="eyebrow">TEAM DISCUSSIONS</p><h1>项目讨论区<span class="logo-dot">.</span></h1><p>选一个你已加入的项目，与队友继续讨论。</p></section>
    <div class="grid">${joined.map(item => `<a class="panel discussion-card" href="#discussion/${item.id}"><span class="chip">${item.ownerId === state.me.id ? "我发起的" : "已加入"}</span><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.description)}</p><span class="discussion-card-link">进入讨论 · ${item.members.length} 位成员 ↗</span></a>`).join("") || `<p class="empty">你还没有加入项目。可以先<a href="#projects">发现项目</a>，申请通过后再来讨论。</p>`}</div>`;
}

function renderDiscussion(id) {
  if (!state.me) return renderAuth("login");
  const item = project(id);
  if (!item) return missing("这个项目不存在");
  if (!item.members.includes(state.me.id)) return missing("只有项目正式成员可以查看讨论区");
  return `<div class="breadcrumbs"><a href="#discussions">项目讨论区</a> / ${escapeHtml(item.title)}</div>
    <section class="page-intro"><p class="eyebrow">TEAM ROOM</p><h1>${escapeHtml(item.title)}<span class="logo-dot">.</span></h1><p>仅项目正式成员可以查看和发言。<a href="#project/${item.id}">查看项目详情 ↗</a></p></section>
    <div class="layout-two"><section class="panel content-panel"><h2>小组讨论</h2><div id="message-list" class="message-list" data-project="${item.id}" aria-live="polite"><p class="small-note">正在读取讨论内容…</p></div>
      <form id="message-form" data-project="${item.id}"><label class="field">发一条消息<textarea name="content" maxlength="500" required rows="3" placeholder="写下想法、进展或需要队友帮忙的事">${escapeHtml(discussionDrafts.get(item.id) || "")}</textarea></label><button class="button" type="submit">发送消息 ↗</button></form></section>
      <aside class="panel content-panel"><h2>小组成员</h2>${item.members.map(userId => { const member = person(userId); return member ? `<div class="member-row">${avatar(member)}<a href="#card/${member.id}">${escapeHtml(member.name)}</a><small>${member.id === item.ownerId ? "队长" : "成员"}</small></div>` : ""; }).join("")}</aside></div>`;
}

function messageItem(row) {
  const author = person(row.userId);
  const name = author?.name || "曾经的成员";
  const time = new Date(row.createdAt).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" });
  return `<article class="message-item ${row.kind === "exit" ? "exit-message" : ""}"><div class="message-meta"><strong>${escapeHtml(name)}</strong><time datetime="${escapeHtml(row.createdAt)}">${escapeHtml(time)}</time></div><p>${row.kind === "exit" ? "退出项目，理由：" : ""}${escapeHtml(row.content)}</p></article>`;
}

async function refreshMessages(force = false) {
  const [route, rawId] = location.hash.slice(1).split("/");
  const projectId = Number(rawId);
  if (route !== "discussion" || !Number.isInteger(projectId) || !project(projectId)?.members.includes(state.me?.id)) return;
  const generation = ++messageGeneration;
  try {
    const result = await api(`/projects/${projectId}/messages`);
    if (generation !== messageGeneration) return;
    const list = document.querySelector("#message-list");
    if (!list || list.dataset.project !== String(projectId)) return;
    const snapshot = JSON.stringify({ projectId, messages: result.messages });
    if (snapshot === lastMessages && !force && list.dataset.loaded === "true") return;
    lastMessages = snapshot;
    list.innerHTML = result.messages.map(messageItem).join("") || `<p class="small-note">还没有消息，发出第一条讨论吧。</p>`;
    list.dataset.loaded = "true";
  } catch (error) { if (force) showToast(error.message); }
}

function identityCard(user) {
  return `<div class="identity-card"><p class="eyebrow">HELLO, I AM</p><h2>${escapeHtml(user.name)} ↗</h2><p>${escapeHtml(user.bio || "写下一句介绍，让大家更快认识你。")}</p><div class="tag-row">${tags([...user.skills, ...user.interests], 4)}</div></div>`;
}

function renderEditProfile() {
  const user = activePerson();
  if (!user) return renderAuth("login");
  return `<div class="breadcrumbs"><a href="#profile">我的名片</a> / 编辑</div><section class="page-intro"><p class="eyebrow">EDIT YOUR CARD</p><h1>编辑我的名片<span class="logo-dot">.</span></h1><p>保存后返回名片展示页。未保存的输入不会改变名片。</p></section>
    <div class="layout-two"><form id="profile-form" class="panel form-panel">
      <div class="form-grid"><label class="field">昵称<input name="name" maxlength="30" required value="${escapeHtml(user.name)}"></label>
      <label class="field">一句身份介绍<input name="role" maxlength="40" value="${escapeHtml(user.role)}" placeholder="例如：开发者、设计师"></label>
      <label class="field">你擅长什么<input name="skills" maxlength="160" required value="${escapeHtml(user.skills.join("，"))}"><span class="hint">多个技能用逗号分隔</span></label>
      <label class="field">感兴趣的方向<input name="interests" maxlength="160" required value="${escapeHtml(user.interests.join("，"))}"></label>
      <label class="field">每周可投入（小时）<input name="hours" type="number" min="1" max="168" required value="${user.hours}"></label></div>
      <label class="field">一句话介绍<textarea name="bio" maxlength="500" rows="4">${escapeHtml(user.bio)}</textarea></label>
      <label class="field">联系方式（可选）<input name="contact" maxlength="120" value="${escapeHtml(user.contact || "")}"></label>
      <label class="checkbox"><input name="showContact" type="checkbox" ${user.showContact ? "checked" : ""}>在公开名片上显示联系方式</label>
      <button class="button" type="submit">保存我的名片 ↗</button> <a class="button button-light" href="#profile">取消</a></form>
      <aside class="stack">${identityCard(user)}<div class="panel content-panel"><h2>名片会展示什么？</h2><p class="small-note">昵称、技能、兴趣、每周可投入时间和简介会公开。联系方式只有勾选后才会显示。</p></div></aside></div>`;
}

function renderProfile(subpage) {
  if (!state.me) return renderAuth("login");
  return subpage === "edit" ? renderEditProfile() : renderCard(state.me.id, true);
}

function renderCard(id, ownPage = false) {
  const user = person(id);
  if (!user) return missing("这张名片不存在");
  const joined = state.projects.filter(item => item.members.includes(user.id));
  return `${ownPage ? "" : `<div class="breadcrumbs"><a href="#people">认识伙伴</a> / ${escapeHtml(user.name)} 的名片</div>`}
    <section class="page-intro"><p class="eyebrow">PERSONAL CARD</p><h1>${ownPage ? "我的名片" : `认识 ${escapeHtml(user.name)}`}<span class="logo-dot">.</span></h1><p>${ownPage ? "这里展示已保存的内容。需要修改时，点击编辑名片。" : "从技能和兴趣开始，聊聊可能一起做的事。"}</p></section>
    <div class="layout-two"><div>${identityCard(user)}<div class="panel content-panel identity-details">
      <h2>更多关于我</h2><p><strong>擅长</strong>${escapeHtml(user.skills.join(" · ")) || "未填写"}</p>
      <p><strong>感兴趣</strong>${escapeHtml(user.interests.join(" · ")) || "未填写"}</p>
      <p><strong>可投入</strong>${user.hours ? `每周 ${user.hours} 小时` : "未填写"}</p>
      ${user.showContact && user.contact ? `<p><strong>联系我</strong>${escapeHtml(user.contact)}</p>` : ""}</div>
      <section class="panel content-panel participation"><h2>已参与项目 <span>${joined.length}</span></h2>
      ${joined.map(item => `<a class="participation-item" href="#project/${item.id}"><div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.category)} · ${item.members.length}/${item.capacity} 人</small></div><span>${item.ownerId === user.id ? "发起人" : "成员"} ↗</span></a>`).join("") || `<p class="small-note">还没有正式加入或发起项目。</p>`}
      </section></div>
      <aside class="panel content-panel"><h2>分享这张名片</h2><p class="small-note">复制链接，发给能访问同一服务的伙伴。</p>
      <button class="button" type="button" data-action="share" data-user="${user.id}">复制名片链接</button>
      ${user.id === state.me?.id ? `<p><a class="button button-light" href="#profile/edit">编辑名片 ↗</a></p>` : ""}</aside></div>`;
}

function scoreRows(result) {
  const rows = [
    ["技能匹配", result.skillPoints, 60, result.skillHits.length ? `命中：${result.skillHits.join("、")}` : "目前没有命中所需技能"],
    ["方向契合", result.topicPoints, 25, result.topicHits.length ? `共同方向：${result.topicHits.join("、")}` : "目前没有共同方向"],
    ["时间投入", result.timePoints, 15, `你每周可投入 ${activePerson().hours} 小时`]
  ];
  return rows.map(([label, points, max, reason]) => `<div class="score-row"><div class="score-row-head"><strong>${label}</strong><span>${points} / ${max}</span></div><div class="score-track"><i style="width:${Math.round(points / max * 100)}%"></i></div><span class="reason">${escapeHtml(reason)}</span></div>`).join("");
}

function renderProject(id) {
  const item = project(id);
  if (!item) return missing("这个项目不存在");
  const user = activePerson();
  const result = match(user, item);
  const application = state.applications.find(row => row.projectId === item.id && row.userId === user?.id);
  const full = memberCount(item) >= item.capacity;
  let action = user ? `<button class="button" type="button" data-action="apply" data-project="${item.id}">申请加入这个项目 ↗</button>` : `<a class="button" href="#login">登录后申请加入 ↗</a>`;
  if (user && item.ownerId === user.id) action = `<div class="status-note">这是你发起的项目。到申请箱查看伙伴的申请。</div><a class="button button-light" href="#inbox">打开申请箱</a><a class="button" href="#discussion/${item.id}">进入项目讨论区 ↗</a>`;
  else if (user && item.members.includes(user.id)) action = `<div class="status-note">你已经加入这个项目。</div><a class="button" href="#discussion/${item.id}">进入项目讨论区 ↗</a>
    <form id="leave-form" class="leave-form" data-project="${item.id}"><label class="field">退出理由<textarea name="reason" maxlength="500" required rows="3" placeholder="告诉队友你为什么退出">${escapeHtml(leaveDrafts.get(item.id) || "")}</textarea></label><p class="small-note">提交后会立即退出，理由会留在小组讨论区。</p><button class="button button-light" type="submit">退出项目</button></form>`;
  else if (application && application.status !== "left") action = `<div class="status-note">你的申请：${{ pending: "等待发起人处理", accepted: "已接受", rejected: "已拒绝" }[application.status]}</div>`;
  else if (full) action = `<div class="status-note">项目已满员，暂时无法申请。</div>`;
  return `<div class="breadcrumbs"><a href="#projects">发现项目</a> / ${escapeHtml(item.title)}</div>
    <section class="page-intro"><p class="eyebrow">OPEN PROJECT / ${String(item.id).padStart(2, "0")}</p><h1>${escapeHtml(item.title)}<span class="logo-dot">.</span></h1><p>由 ${escapeHtml(ownerName(item))} 发起 · ${full ? "已满员" : "正在寻找队友"}</p></section>
    <div class="layout-two"><div class="stack"><section class="panel content-panel"><span class="chip">${escapeHtml(item.category)}</span><h2 style="margin-top:20px">这个项目想做什么</h2><p class="lead">${escapeHtml(item.description)}</p>
      <div class="detail-meta"><div><small>需要的技能</small><strong>${escapeHtml(item.needs.join(" · "))}</strong></div><div><small>项目方向</small><strong>${escapeHtml(item.topics.join(" · "))}</strong></div>
      <div><small>每周希望投入</small><strong>至少 ${item.minHours} 小时</strong></div><div><small>队伍名额</small><strong>${memberCount(item)} / ${item.capacity} 人</strong></div></div>
      <h2>已经在队伍里</h2>${item.members.map(userId => { const member = person(userId); return `<div class="member-row">${avatar(member)}<a href="#card/${member.id}">${escapeHtml(member.name)}</a><small>${userId === item.ownerId ? "发起人" : "成员"}</small></div>`; }).join("")}</section></div>
      <aside class="panel content-panel side-panel"><p class="eyebrow">YOUR MATCH</p><h2>你与这个项目的匹配</h2>
      ${result ? `<div class="side-score">${result.total}<small> / 100</small></div>${scoreRows(result)}` : `<p class="small-note">${user ? "完善名片后才能计算匹配指数。" : "登录并完善名片后可查看匹配指数。"}</p>`}
      <p class="small-note">指数只比较技能、兴趣和可投入时间。是否适合合作，还要靠交流判断。</p>${action}</aside></div>`;
}

function renderCreate() {
  if (!state.me) return renderAuth("login");
  return `<section class="page-intro"><p class="eyebrow">START SOMETHING</p><h1>让你的想法找到队友<span class="logo-dot">.</span></h1><p>把问题和需要的技能讲清楚，让对的人找到你。</p></section>
    <div class="layout-two"><form id="project-form" class="panel form-panel"><label class="field">项目名称<input name="title" maxlength="100" required placeholder="例如：校园剩食地图"></label>
      <label class="field">项目简介<textarea name="description" maxlength="1000" required placeholder="想解决什么问题？希望做出什么？"></textarea></label>
      <div class="form-grid"><label class="field">需要的技能<input name="needs" maxlength="160" required placeholder="Python，视觉设计"></label>
      <label class="field">项目方向<input name="topics" maxlength="160" required placeholder="教育，环保"></label>
      <label class="field">每周希望至少投入（小时）<input name="minHours" type="number" min="1" max="168" required value="6"></label>
      <label class="field">队伍人数上限（包括你）<input name="capacity" type="number" min="2" max="20" required value="4"></label></div>
      <button class="button" type="submit">发布项目 ↗</button></form>
      <aside class="panel content-panel"><p class="eyebrow">A GOOD PROJECT POST</p><h2>把招募说具体</h2><p>项目要解决什么问题？希望新队友具备什么技能？大家要投入多少时间？越具体，匹配指数和申请判断越有参考价值。</p></aside></div>`;
}

function renderInbox() {
  if (!state.me) return renderAuth("login");
  const owned = state.projects.filter(item => item.ownerId === state.me.id);
  const requests = state.applications.filter(row => row.status === "pending" && owned.some(item => item.id === row.projectId));
  return `<section class="page-intro"><p class="eyebrow">APPLICATIONS</p><h1>你的申请箱<span class="logo-dot">.</span></h1><p>先看看申请者名片，再决定是否一起行动。</p></section>
    <div class="section-head"><h2>待处理申请</h2><span class="small-note">${requests.length} 条</span></div>
    ${requests.map(row => { const user = person(row.userId); const item = project(row.projectId); return `<article class="panel request"><div class="request-left">${avatar(user)}<div><h3><a href="#card/${user.id}">${escapeHtml(user.name)}</a> 申请加入 <a href="#project/${item.id}">${escapeHtml(item.title)}</a></h3><p>${escapeHtml(user.skills.join(" · "))} · 每周 ${user.hours} 小时</p></div></div>
      <div class="request-actions"><button class="button button-small" type="button" data-action="decide" data-id="${row.id}" data-decision="accept">接受</button><button class="button button-light button-small" type="button" data-action="decide" data-id="${row.id}" data-decision="reject">拒绝</button></div></article>`; }).join("") || `<p class="empty">目前没有待处理申请。你可以先<a href="#create">发起项目</a>，或稍后再来看看。</p>`}
    <p class="small-note">你发起的项目：${owned.length ? owned.map(item => `<a href="#project/${item.id}">${escapeHtml(item.title)}</a>`).join(" · ") : "暂无"}</p>`;
}

function missing(message) { return `<section class="page-intro"><h1>${escapeHtml(message)}</h1><p><a class="button" href="#projects">返回项目首页</a></p></section>`; }

function renderAuth(mode) {
  const registering = mode === "register";
  return `<section class="page-intro"><p class="eyebrow">${registering ? "JOIN TONGPIN" : "WELCOME BACK"}</p><h1>${registering ? "创建账号" : "登录同频"}<span class="logo-dot">.</span></h1><p>使用自己的账号，和现场伙伴共享最新的项目与申请状态。</p></section>
    <form id="auth-form" class="panel form-panel auth-panel" data-mode="${mode}">
      <label class="field">昵称<input name="nickname" maxlength="30" required autocomplete="username" placeholder="输入昵称"></label>
      <label class="field">密码<input name="password" type="password" minlength="8" maxlength="128" required autocomplete="${registering ? "new-password" : "current-password"}" placeholder="至少 8 位"></label>
      <button class="button" type="submit">${registering ? "注册并制作名片" : "登录"} ↗</button>
      <p class="small-note">${registering ? `已有账号？<a href="#login">去登录</a>` : `还没有账号？<a href="#register">先注册</a>`}</p>
    </form>`;
}

function render() {
  const [route, id] = (location.hash.slice(1) || "projects").split("/");
  updateHeader(route === "discussion" ? "discussions" : route);
  const pages = { projects: renderProjects, people: renderPeople, discussions: renderDiscussions, profile: () => renderProfile(id), inbox: renderInbox, create: renderCreate, login: () => renderAuth("login"), register: () => renderAuth("register") };
  app.innerHTML = route === "project" ? renderProject(id) : route === "discussion" ? renderDiscussion(id) : route === "card" ? renderCard(id) : pages[route]?.() || missing("页面不存在");
  document.title = `${({ projects: "发现项目", people: "认识伙伴", discussions: "项目讨论区", discussion: "项目讨论区" })[route] || "同频"} · 同频`;
  if (route === "discussion") refreshMessages(true);
}

function splitTags(value) { return [...new Set(value.split(/[,，、]/).map(item => item.trim()).filter(Boolean))]; }

document.addEventListener("input", event => {
  const form = event.target.closest("#message-form, #leave-form");
  if (!form) return;
  const projectId = Number(form.dataset.project);
  if (form.id === "message-form") discussionDrafts.set(projectId, event.target.value);
  if (form.id === "leave-form") leaveDrafts.set(projectId, event.target.value);
});

document.addEventListener("submit", async event => {
  const form = event.target;
  if (form.id === "search-form") {
    event.preventDefault();
    searchQuery = new FormData(form).get("query").toString();
    render();
    return;
  }
  if (!["auth-form", "profile-form", "project-form", "message-form", "leave-form"].includes(form.id)) return;
  event.preventDefault();
  const data = new FormData(form);
  try {
    if (form.id === "message-form") {
      const projectId = Number(form.dataset.project);
      const content = data.get("content").trim();
      if (!content) return showToast("请输入讨论内容。");
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        const result = await api(`/projects/${projectId}/messages`, "POST", { content });
        discussionDrafts.delete(projectId);
        form.elements.content.value = "";
        form.elements.content.defaultValue = "";
        await refreshMessages(true);
        showToast(result.message);
      } finally { button.disabled = false; }
      return;
    }
    if (form.id === "leave-form") {
      const projectId = Number(form.dataset.project);
      const reason = data.get("reason").trim();
      if (!reason) return showToast("请填写退出理由。");
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        const result = await api(`/projects/${projectId}/leave`, "POST", { reason });
        leaveDrafts.delete(projectId);
        await refresh(true);
        showToast(result.message);
      } finally { button.disabled = false; }
      return;
    }
    if (form.id === "auth-form") {
      const registering = form.dataset.mode === "register";
      const result = await api(registering ? "/register" : "/login", "POST", {
        nickname: data.get("nickname").trim(), password: data.get("password")
      });
      state.csrfToken = result.csrfToken;
      await refresh(true);
      location.hash = registering ? "#profile" : "#projects";
      render(); showToast(result.message);
    }
    if (form.id === "profile-form") {
      const skills = splitTags(data.get("skills"));
      const interests = splitTags(data.get("interests"));
      if (!skills.length || !interests.length) return showToast("请至少填写一项技能和兴趣。");
      const result = await api("/profile", "PUT", {
        name: data.get("name").trim(), role: data.get("role").trim(), skills, interests,
        hours: Number(data.get("hours")), bio: data.get("bio").trim(),
        contact: data.get("contact").trim(), showContact: data.has("showContact")
      });
      await refresh(true);
      location.hash = "#profile";
      render(); showToast(result.message);
    }
    if (form.id === "project-form") {
      const needs = splitTags(data.get("needs"));
      const topics = splitTags(data.get("topics"));
      if (!needs.length || !topics.length) return showToast("请填写技能和项目方向。");
      const result = await api("/projects", "POST", {
        title: data.get("title").trim(), description: data.get("description").trim(),
        needs, topics, minHours: Number(data.get("minHours")), capacity: Number(data.get("capacity"))
      });
      await refresh(true);
      location.hash = `#project/${result.id}`;
      render(); showToast(result.message);
    }
  } catch (error) { showToast(error.message); }
});

document.addEventListener("click", async event => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  try {
    if (button.dataset.action === "apply") {
      const result = await api(`/projects/${Number(button.dataset.project)}/apply`, "POST");
      await refresh(true); showToast(result.message);
    }
    if (button.dataset.action === "decide") {
      const result = await api(`/applications/${Number(button.dataset.id)}/decision`, "POST", { decision: button.dataset.decision });
      await refresh(true); showToast(result.message);
    }
    if (button.dataset.action === "logout") {
      const result = await api("/logout", "POST");
      state.csrfToken = result.csrfToken;
      location.hash = "#projects";
      await refresh(true); showToast(result.message);
    }
    if (button.dataset.action === "share") {
      const url = new URL(location.href);
      url.hash = `card/${Number(button.dataset.user)}`;
      try { await navigator.clipboard.writeText(url.href); showToast("名片链接已复制。"); }
      catch (_) { window.prompt("复制这个名片链接：", url.href); }
    }
  } catch (error) { showToast(error.message); }
});

window.addEventListener("hashchange", render);
if (!location.hash) location.hash = "#projects";
app.innerHTML = `<p class="empty">正在读取最新数据…</p>`;
refresh(true);
setInterval(async () => { if (!document.hidden) { await refresh(); await refreshMessages(); } }, 2500);
document.addEventListener("visibilitychange", async () => { if (!document.hidden) { await refresh(); await refreshMessages(); } });
