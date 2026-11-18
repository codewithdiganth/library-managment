const featurePanel = document.querySelector("#feature-panel");
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
const userRole = document.body.dataset.role || "";

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      "X-CSRF-Token": csrfToken,
      ...options.headers,
    },
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || "The request could not be completed.");
  return result;
}

function notify(message, type = "success") {
  let toast = document.querySelector(".toast-message");
  if (!toast) {
    toast = document.createElement("div");
    toast.className = "toast-message";
    toast.setAttribute("role", "status");
    document.body.append(toast);
  }
  toast.className = `toast-message is-visible ${type}`;
  toast.textContent = message;
  window.clearTimeout(notify.timeout);
  notify.timeout = window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
}

function panelHeading(kicker, title, description, action = "") {
  return `<div class="feature-heading"><div><span class="eyebrow">${kicker}</span><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
}

function bookDialogMarkup() {
  return `<dialog class="form-dialog" id="book-dialog"><form id="book-form" method="dialog"><div class="dialog-head"><div><span class="eyebrow">CATALOG RECORD</span><h2 id="book-dialog-title">Add a book</h2></div><button class="icon-button dialog-close" value="cancel" aria-label="Close">×</button></div><input type="hidden" name="id"><div class="form-grid"><label>ISBN<input name="isbn" required maxlength="13" inputmode="numeric"></label><label>Title<input name="title" required maxlength="160"></label><label>Author<input name="author" required maxlength="160"></label><label>Category<input name="category" required maxlength="60"></label><label>Total copies<input name="total_copies" type="number" min="0" max="500" value="1" required></label><label>Cover image URL<input name="cover_url" type="url" placeholder="https://..."></label><label>Floor<input name="floor" value="1"></label><label>Shelf<input name="shelf" value="A"></label><label>Rack<input name="rack" value="01"></label><label class="form-full">Description<textarea name="description" rows="3" maxlength="500"></textarea></label></div><div class="dialog-actions"><button class="button button-quiet" type="button" data-close-dialog>Cancel</button><button class="button button-primary" type="submit">Save book</button></div></form></dialog>`;
}

function renderBookCard(book) {
  const cover = document.createElement("article");
  cover.className = "catalog-card";
  const coverBox = document.createElement("div");
  coverBox.className = `catalog-cover cover-tone-${(book.category || "book").toLowerCase().replace(/[^a-z]/g, "").slice(0, 12)}`;

  // Typographic fallback cover ensures book covers are never blank
  const fallback = document.createElement("div");
  fallback.className = "catalog-cover-fallback";
  fallback.innerHTML = `<span class="fallback-author">${escapeHtml(book.author)}</span><b class="fallback-title">${escapeHtml(book.title)}</b><span class="fallback-cat">${escapeHtml(book.category)}</span>`;
  coverBox.append(fallback);

  if (book.cover_url && /^https:\/\//i.test(book.cover_url)) {
    const image = document.createElement("img");
    image.src = book.cover_url;
    image.alt = `Cover of ${book.title}`;
    image.loading = "lazy";
    image.onerror = () => image.remove();
    coverBox.append(image);
  }

  const availability = document.createElement("span");
  availability.className = `availability ${book.available_copies > 0 ? "available" : "unavailable"}`;
  availability.textContent = book.available_copies > 0 ? `${book.available_copies} available` : "All copies loaned";
  coverBox.append(availability);

  const body = document.createElement("div");
  body.className = "catalog-card-body";
  body.innerHTML = `<span class="book-category">${escapeHtml(book.category)}</span><h3>${escapeHtml(book.title)}</h3><p>${escapeHtml(book.author)}</p><div class="book-location">Floor ${escapeHtml(book.floor)} · Shelf ${escapeHtml(book.shelf)} · Rack ${escapeHtml(book.rack)}</div>`;

  if (["admin", "staff"].includes(userRole)) {
    const actions = document.createElement("div");
    actions.className = "catalog-actions";
    actions.innerHTML = `<button type="button" data-edit-book="${book.id}">Edit</button><button type="button" data-delete-book="${book.id}">Remove</button>`;
    body.append(actions);
  }
  if (userRole === "student" && book.available_copies === 0) {
    const queueAction = document.createElement("button");
    queueAction.className = "queue-book-action";
    queueAction.type = "button";
    queueAction.dataset.joinQueue = book.id;
    queueAction.textContent = "Join waiting queue";
    body.append(queueAction);
  }
  cover.append(coverBox, body);
  return cover;
}

async function showCatalog() {
  const canManage = ["admin", "staff"].includes(userRole);
  featurePanel.innerHTML = `${panelHeading("COLLECTION", "Discover books", "Search by title, author, ISBN or subject.", canManage ? '<button class="button button-primary" id="add-book"><span>＋</span> Add a book</button>' : "")}<div class="catalog-toolbar"><label class="search-field"><span aria-hidden="true">⌕</span><input id="book-search" type="search" placeholder="Try a title, author or ISBN" autocomplete="off"></label><select id="category-filter" aria-label="Filter by category"><option value="">All categories</option></select><label class="check-filter"><input id="available-filter" type="checkbox"> Available now</label></div><p class="result-count" id="book-count" aria-live="polite"></p><div class="catalog-grid" id="book-results"></div>${bookDialogMarkup()}`;
  const search = featurePanel.querySelector("#book-search");
  const category = featurePanel.querySelector("#category-filter");
  const availability = featurePanel.querySelector("#available-filter");
  const resultGrid = featurePanel.querySelector("#book-results");
  const count = featurePanel.querySelector("#book-count");
  const dialog = featurePanel.querySelector("#book-dialog");
  const form = featurePanel.querySelector("#book-form");
  let timer;

  const load = async () => {
    const params = new URLSearchParams({ q: search.value, category: category.value, available: availability.checked ? "1" : "" });
    try {
      const result = await api(`/api/books?${params}`);
      const previous = category.value;
      category.innerHTML = '<option value="">All categories</option>' + result.categories.map((value) => `<option>${escapeHtml(value)}</option>`).join("");
      category.value = result.categories.includes(previous) ? previous : "";
      resultGrid.replaceChildren(...result.books.map(renderBookCard));
      count.textContent = `${result.books.length} ${result.books.length === 1 ? "title" : "titles"}`;
      if (!result.books.length) resultGrid.innerHTML = '<div class="empty-state"><span>⌕</span><b>No matches yet</b><p>Try a different search or clear a filter.</p></div>';
    } catch (error) { notify(error.message, "error"); }
  };

  search.addEventListener("input", () => { window.clearTimeout(timer); timer = window.setTimeout(load, 220); });
  category.addEventListener("change", load);
  availability.addEventListener("change", load);

  featurePanel.querySelector("#add-book")?.addEventListener("click", () => {
    form.reset(); form.elements.id.value = ""; form.elements.total_copies.value = 1;
    featurePanel.querySelector("#book-dialog-title").textContent = "Add a book";
    dialog.showModal();
  });

  featurePanel.addEventListener("click", async (event) => {
    const queueButton = event.target.closest("[data-join-queue]");
    if (queueButton) {
      try {
        await api("/api/queue", { method: "POST", body: JSON.stringify({ book_id: Number(queueButton.dataset.joinQueue) }) });
        queueButton.disabled = true;
        queueButton.textContent = "Added to your queue";
        notify("You joined the waiting queue.");
      } catch (error) { notify(error.message, "error"); }
      return;
    }
    const edit = event.target.closest("[data-edit-book]");
    const remove = event.target.closest("[data-delete-book]");
    if (edit) {
      const book = (await api("/api/books")).books.find((item) => item.id === Number(edit.dataset.editBook));
      if (!book) return;
      for (const [key, value] of Object.entries(book)) if (form.elements[key]) form.elements[key].value = value;
      form.elements.id.value = book.id;
      featurePanel.querySelector("#book-dialog-title").textContent = "Edit book details";
      dialog.showModal();
    }
    if (remove && window.confirm("Remove this book from the catalog?")) {
      try { await api(`/api/books/${remove.dataset.deleteBook}`, { method: "DELETE" }); notify("Book removed from the catalog."); await load(); }
      catch (error) { notify(error.message, "error"); }
    }
  });

  featurePanel.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    const id = data.id; delete data.id; data.total_copies = Number(data.total_copies);
    try {
      await api(id ? `/api/books/${id}` : "/api/books", { method: id ? "PATCH" : "POST", body: JSON.stringify(data) });
      dialog.close(); notify(id ? "Book details updated." : "Book added to the catalog."); await load();
    } catch (error) { notify(error.message, "error"); }
  });
  await load();
}

function memberDialogMarkup() {
  return `<dialog class="form-dialog" id="member-dialog"><form id="member-form" method="dialog"><div class="dialog-head"><div><span class="eyebrow">MEMBER PROFILE</span><h2 id="member-dialog-title">Add a student</h2></div><button class="icon-button dialog-close" value="cancel" aria-label="Close">×</button></div><input type="hidden" name="id"><div class="form-grid"><label>Full name<input name="name" required maxlength="120"></label><label>University email<input name="email" required type="email" maxlength="200"></label><label>Department<input name="department" maxlength="100"></label><label id="member-password-field">Password<input name="password" type="password" minlength="8" autocomplete="new-password" placeholder="Min 8 characters"></label><label id="member-active-field" style="display:none;">Status<select name="active"><option value="1">Active</option><option value="0">Inactive</option></select></label></div><div class="dialog-actions"><button class="button button-quiet" type="button" data-close-dialog>Cancel</button><button class="button button-primary" type="submit">Save member</button></div></form></dialog>`;
}

async function showMembers() {
  featurePanel.innerHTML = `${panelHeading("PEOPLE", "Member management", "Student profiles, borrowing history and account status.", userRole === "admin" ? '<button class="button button-primary" id="add-member">＋ Add member</button>' : "")}<div class="table-wrap"><table class="data-table"><thead><tr><th>Member</th><th>Department</th><th>Borrowing</th><th>Status</th><th>History</th>${userRole === "admin" ? "<th>Actions</th>" : ""}</tr></thead><tbody id="member-rows"></tbody></table></div><section id="member-history" class="history-panel" hidden></section>${memberDialogMarkup()}`;
  const rows = featurePanel.querySelector("#member-rows");
  const dialog = featurePanel.querySelector("#member-dialog");
  const form = featurePanel.querySelector("#member-form");

  const load = async () => {
    try {
      const { members } = await api("/api/members");
      rows.innerHTML = members.map((member) => `<tr><td><div class="member-cell"><span class="avatar">${escapeHtml(member.name.slice(0, 1))}</span><span><b>${escapeHtml(member.name)}</b><small>${escapeHtml(member.email)} · ${escapeHtml(member.member_code || "")}</small></span></div></td><td>${escapeHtml(member.department || "—")}</td><td>${member.active_loans || 0} active <small> · ${member.loans_count || 0} total</small></td><td><span class="status-pill ${member.active ? "status-active" : "status-inactive"}">${member.active ? "Active" : "Inactive"}</span></td><td><button class="table-action" data-member-history="${member.id}">View history</button></td>${userRole === "admin" ? `<td><button class="table-action" data-edit-member="${member.id}">Edit</button> <button class="table-action danger-link" data-remove-member="${member.id}">${member.active ? "Deactivate" : "Activate"}</button></td>` : ""}</tr>`).join("");
      rows.dataset.members = JSON.stringify(members);
      if (!members.length) rows.innerHTML = '<tr><td colspan="6">No student accounts found.</td></tr>';
    } catch (error) { notify(error.message, "error"); }
  };

  featurePanel.querySelector("#add-member")?.addEventListener("click", () => {
    form.reset(); form.elements.id.value = ""; form.elements.password.required = true;
    featurePanel.querySelector("#member-password-field").style.display = "grid";
    featurePanel.querySelector("#member-active-field").style.display = "none";
    featurePanel.querySelector("#member-dialog-title").textContent = "Add a student"; dialog.showModal();
  });

  featurePanel.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  featurePanel.addEventListener("click", async (event) => {
    const historyButton = event.target.closest("[data-member-history]");
    const edit = event.target.closest("[data-edit-member]");
    const remove = event.target.closest("[data-remove-member]");
    if (historyButton) {
      try {
        const result = await api(`/api/members/${historyButton.dataset.memberHistory}/history`);
        const history = featurePanel.querySelector("#member-history");
        history.hidden = false;
        history.innerHTML = `<div class="history-head"><div><span class="eyebrow">BORROWING RECORD</span><h2>${escapeHtml(result.member.name)}</h2></div><button class="text-button" data-hide-history>Close</button></div>${result.history.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Title</th><th>Issued</th><th>Due</th><th>Returned</th><th>Fine</th></tr></thead><tbody>${result.history.map((item) => `<tr><td>${escapeHtml(item.title)}</td><td>${escapeHtml(item.issued_at)}</td><td>${escapeHtml(item.due_at)}</td><td>${escapeHtml(item.returned_at || "On loan")}</td><td>Rs. ${Number(item.fine).toFixed(2)}</td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">No borrowing history yet.</p>'}`;
      } catch (error) { notify(error.message, "error"); }
    }
    if (event.target.closest("[data-hide-history]")) featurePanel.querySelector("#member-history").hidden = true;
    if (edit) {
      const member = JSON.parse(rows.dataset.members || "[]").find((item) => item.id === Number(edit.dataset.editMember));
      if (!member) return;
      for (const key of ["name", "email", "department"]) form.elements[key].value = member[key] || "";
      form.elements.id.value = member.id;
      form.elements.password.value = "";
      form.elements.password.required = false;
      form.elements.active.value = member.active ? "1" : "0";
      featurePanel.querySelector("#member-password-field").style.display = "grid";
      featurePanel.querySelector("#member-active-field").style.display = "grid";
      featurePanel.querySelector("#member-dialog-title").textContent = "Edit member"; dialog.showModal();
    }
    if (remove) {
      const memberId = Number(remove.dataset.removeMember);
      const member = JSON.parse(rows.dataset.members || "[]").find((item) => item.id === memberId);
      if (member && member.active) {
        if (window.confirm("Deactivate this member account? Borrowing history will be preserved.")) {
          try { await api(`/api/members/${memberId}`, { method: "DELETE" }); notify("Member deactivated."); await load(); }
          catch (error) { notify(error.message, "error"); }
        }
      } else {
        try { await api(`/api/members/${memberId}`, { method: "PATCH", body: JSON.stringify({ active: 1 }) }); notify("Member reactivated."); await load(); }
        catch (error) { notify(error.message, "error"); }
      }
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    const id = data.id; delete data.id;
    if (!data.password) delete data.password;
    try {
      await api(id ? `/api/members/${id}` : "/api/members", { method: id ? "PATCH" : "POST", body: JSON.stringify(data) });
      dialog.close(); notify(id ? "Member updated." : "Student account created."); await load();
    } catch (error) { notify(error.message, "error"); }
  });
  await load();
}

async function showCirculation() {
  featurePanel.innerHTML = `${panelHeading("LOANS DESK", "Circulation", "Issue and return books with a clear borrowing record.")}<div class="segmented-control"><button class="active" data-circulation-mode="issue">Issue a book</button><button data-circulation-mode="return">Return a book</button></div><div class="circulation-layout"><section class="circulation-form-area"><div class="circulation-intro"><span class="eyebrow" id="circulation-kicker">NEW LOAN</span><h2 id="circulation-title">Check out a title</h2><p id="circulation-description">Enter the member code and book ISBN to start a 14-day loan.</p></div><form id="circulation-form" class="circulation-form"><label>Member code<input name="member_code" id="circ-member-code" placeholder="STU-2401" required autocomplete="off"></label><label>Book ISBN<input name="isbn" id="circ-isbn" placeholder="13-digit ISBN" required autocomplete="off"></label><label id="loan-days-field">Loan period<select name="days"><option value="14">14 days</option><option value="7">7 days</option><option value="21">21 days</option></select></label><div style="display:flex;gap:8px;margin-top:8px;"><button class="button button-primary" type="submit" id="circulation-submit" style="flex:1;">Confirm issue <span>→</span></button><button class="button button-quiet" type="button" id="circ-scan-btn" title="Open camera barcode/QR scanner">📷 Scan</button></div></form><div class="qr-hint"><span>▦</span><p>Member and book QR codes can be scanned from the digital record.<small>Camera and barcode scanning is available in Smart scanner.</small></p></div></section><section class="circulation-recent"><div class="subsection-heading"><div><span class="eyebrow">IN THE LIBRARY</span><h2>Active loans</h2></div><button class="text-button" id="refresh-loans">Refresh</button></div><div id="active-loans" class="active-loan-list"></div></section></div>`;
  const form = featurePanel.querySelector("#circulation-form");
  let mode = "issue";

  const setMode = (next) => {
    mode = next;
    featurePanel.querySelectorAll("[data-circulation-mode]").forEach((button) => button.classList.toggle("active", button.dataset.circulationMode === next));
    featurePanel.querySelector("#circulation-kicker").textContent = next === "issue" ? "NEW LOAN" : "RETURN DESK";
    featurePanel.querySelector("#circulation-title").textContent = next === "issue" ? "Check out a title" : "Check in a title";
    featurePanel.querySelector("#circulation-description").textContent = next === "issue" ? "Enter the member code and book ISBN to start a 14-day loan." : "Enter the member code and book ISBN to close an active loan.";
    featurePanel.querySelector("#loan-days-field").hidden = next !== "issue";
    featurePanel.querySelector("#circulation-submit").innerHTML = `${next === "issue" ? "Confirm issue" : "Complete return"} <span>→</span>`;
  };

  featurePanel.querySelectorAll("[data-circulation-mode]").forEach((button) => button.addEventListener("click", () => setMode(button.dataset.circulationMode)));

  const loadLoans = async () => {
    const result = await api("/api/loans");
    const active = result.loans.filter((loan) => !loan.returned_at);
    const list = featurePanel.querySelector("#active-loans");
    list.innerHTML = active.length ? active.map((loan) => `<article class="active-loan"><div class="loan-details"><b>${escapeHtml(loan.title)}</b><small>${escapeHtml(loan.member_name)} (${escapeHtml(loan.member_code)}) · due ${escapeHtml(loan.due_at)}</small>${loan.current_fine > 0 ? `<em style="color:#d9534f;font-weight:600;">Rs. ${Number(loan.current_fine).toFixed(2)} fine accrued</em>` : ""}</div><div class="loan-qr"><a href="/qr/member/${loan.user_id}.png" target="_blank" title="View Member QR"><img src="/qr/member/${loan.user_id}.png" alt="Member QR code"></a><a href="/qr/book/${loan.book_id}.png" target="_blank" title="View Book QR"><img src="/qr/book/${loan.book_id}.png" alt="Book QR code"></a></div><button class="table-action" data-return-loan="${loan.id}">Return</button></article>`).join("") : '<div class="empty-state"><b>No books are currently on loan</b><p>New checkouts will appear here.</p></div>';
  };

  featurePanel.querySelector("#refresh-loans").addEventListener("click", () => loadLoans().catch((error) => notify(error.message, "error")));
  featurePanel.querySelector("#circ-scan-btn").addEventListener("click", () => {
    openFeature("scanner");
  });

  featurePanel.querySelector("#active-loans").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-return-loan]");
    if (!button) return;
    try {
      const res = await api("/api/circulation/return", { method: "POST", body: JSON.stringify({ loan_id: Number(button.dataset.returnLoan) }) });
      notify(`Book returned successfully. Fine: Rs. ${Number(res.fine).toFixed(2)}.`);
      await loadLoans();
    } catch (error) { notify(error.message, "error"); }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    try {
      const result = await api(`/api/circulation/${mode}`, { method: "POST", body: JSON.stringify(data) });
      notify(mode === "issue" ? `Checked out. Due ${result.due_at}.` : `Returned. Fine: Rs. ${Number(result.fine).toFixed(2)}.`);
      form.reset(); await loadLoans();
    } catch (error) { notify(error.message, "error"); }
  });
  await loadLoans();
}

async function showMyBooks() {
  featurePanel.innerHTML = `${panelHeading("YOUR ACCOUNT", "My books", "Current loans, due dates and your digital member card.")}<div class="member-card"><div><span class="eyebrow">NORTHSTAR MEMBER</span><h2>${escapeHtml(document.querySelector(".user-name")?.childNodes[0]?.textContent?.trim() || "Library member")}</h2><p>Present this QR code at the desk to check out or return books.</p></div><img src="/qr/member/${document.body.dataset.userId}.png" alt="Your member QR code"></div><div class="subsection-heading personal-loans-heading"><div><span class="eyebrow">BORROWING</span><h2>Your loans</h2></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Title</th><th>Checked out</th><th>Due date</th><th>Status</th><th>Fine</th></tr></thead><tbody id="my-loan-rows"></tbody></table></div>`;
  try {
    const { loans } = await api("/api/loans");
    const rows = featurePanel.querySelector("#my-loan-rows");
    rows.innerHTML = loans.length ? loans.map((loan) => `<tr><td><div class="loan-title-cell"><img src="/qr/book/${loan.book_id}.png" alt="Book QR"><span><b>${escapeHtml(loan.title)}</b><small>${escapeHtml(loan.author)}</small></span></div></td><td>${escapeHtml(loan.issued_at)}</td><td>${escapeHtml(loan.due_at)}</td><td><span class="status-pill ${loan.returned_at ? "status-inactive" : loan.due_at < new Date().toISOString().slice(0, 10) ? "status-overdue" : "status-active"}">${loan.returned_at ? "Returned" : loan.due_at < new Date().toISOString().slice(0, 10) ? "Overdue" : "On loan"}</span></td><td>${Number(loan.current_fine) > 0 ? `Rs. ${Number(loan.current_fine).toFixed(2)}${loan.fine_paid ? " · paid" : ` <button class="table-action" data-pay-fine="${loan.id}">Pay</button>`}` : "—"}</td></tr>`).join("") : '<tr><td colspan="5">No borrowing history yet. Explore the catalog to find your next read.</td></tr>';
    rows.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-pay-fine]");
      if (!button) return;
      try { await api(`/api/fines/${button.dataset.payFine}/pay`, { method: "POST", body: "{}" }); notify("Fine payment recorded."); await showMyBooks(); }
      catch (error) { notify(error.message, "error"); }
    });
  } catch (error) { notify(error.message, "error"); }
}

let analyticsTimer;
let analyticsCharts = [];

async function showAnalytics() {
  window.clearInterval(analyticsTimer);
  analyticsCharts.forEach((chart) => chart.destroy());
  analyticsCharts = [];
  featurePanel.innerHTML = `${panelHeading("LIBRARY INTELLIGENCE", "Analytics", "A live view of borrowing, engagement and study space use.")}<div class="analytics-summary" id="analytics-summary"></div><div class="analytics-grid"><article class="analytics-chart-card chart-wide"><div class="chart-title"><div><span class="eyebrow">CIRCULATION</span><h2>Issues and returns</h2></div><span class="chart-period">Last 14 days</span></div><canvas id="circulation-chart" aria-label="Books issued and returned over the last fourteen days"></canvas></article><article class="analytics-chart-card"><div class="chart-title"><div><span class="eyebrow">COLLECTION</span><h2>Popular titles</h2></div></div><canvas id="popular-chart" aria-label="Most borrowed titles"></canvas></article><article class="analytics-chart-card"><div class="chart-title"><div><span class="eyebrow">COMMUNITY</span><h2>Active members</h2></div></div><canvas id="members-chart" aria-label="Daily active borrowers"></canvas></article><article class="analytics-chart-card"><div class="chart-title"><div><span class="eyebrow">RETURNS</span><h2>Overdue books</h2></div></div><canvas id="overdue-chart" aria-label="Overdue books by number of days"></canvas></article><article class="analytics-chart-card"><div class="chart-title"><div><span class="eyebrow">STUDY SPACES</span><h2>Seat usage now</h2></div></div><canvas id="seats-chart" aria-label="Current seat occupancy"></canvas></article></div><p class="analytics-updated" id="analytics-updated"></p>`;

  const load = async () => {
    try {
      const data = await api("/api/analytics");
      const metricItems = [["Active loans", data.totals.active_loans, "↗"], ["Active members", data.totals.active_members, "♧"], ["Overdue", data.totals.overdue, "!"], ["Catalog titles", data.totals.total_books, "▤"]];
      featurePanel.querySelector("#analytics-summary").innerHTML = metricItems.map(([label, value, icon]) => `<article class="analytics-metric"><span class="analytics-metric-icon">${icon}</span><div><small>${label}</small><b>${value}</b></div></article>`).join("");
      featurePanel.querySelector("#analytics-updated").textContent = `Updated ${new Date(data.updated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · refreshes every 30 seconds`;
      if (!window.Chart) return;
      analyticsCharts.forEach((chart) => chart.destroy());
      const common = { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: "#718096", boxWidth: 9, boxHeight: 9, font: { family: "DM Sans", size: 10 } } } } };
      analyticsCharts = [
        new Chart(featurePanel.querySelector("#circulation-chart"), { type: "line", data: { labels: data.circulation.labels.map((day) => day.slice(5)), datasets: [{ label: "Issued", data: data.circulation.issued, borderColor: "#1769d2", backgroundColor: "#1769d218", fill: true, tension: .35 }, { label: "Returned", data: data.circulation.returned, borderColor: "#50a17a", backgroundColor: "transparent", tension: .35 }] }, options: { ...common, scales: { x: { grid: { display: false }, ticks: { color: "#8a98a9", maxTicksLimit: 7 } }, y: { beginAtZero: true, grid: { color: "#edf1f5" }, ticks: { color: "#8a98a9", precision: 0 } } } } }),
        new Chart(featurePanel.querySelector("#popular-chart"), { type: "bar", data: { labels: data.popular.labels, datasets: [{ data: data.popular.values, backgroundColor: ["#1769d2", "#58a1c9", "#63a47d", "#deaa59", "#db816e", "#8a9ab1"], borderRadius: 3, barThickness: 13 }] }, options: { ...common, indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, grid: { color: "#edf1f5" }, ticks: { color: "#8a98a9", precision: 0 } }, y: { grid: { display: false }, ticks: { color: "#617188", font: { size: 9 } } } } } }),
        new Chart(featurePanel.querySelector("#members-chart"), { type: "line", data: { labels: data.active_members.labels.map((day) => day.slice(5)), datasets: [{ label: "Borrowers", data: data.active_members.values, borderColor: "#4e9a75", backgroundColor: "#4e9a7518", fill: true, tension: .3 }] }, options: { ...common, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { color: "#8a98a9", maxTicksLimit: 6 } }, y: { beginAtZero: true, grid: { color: "#edf1f5" }, ticks: { color: "#8a98a9", precision: 0 } } } } }),
        new Chart(featurePanel.querySelector("#overdue-chart"), { type: "bar", data: { labels: data.overdue.labels, datasets: [{ data: data.overdue.values, backgroundColor: ["#e2af62", "#dc8968", "#bc5b55"], borderRadius: 3, barThickness: 25 }] }, options: { ...common, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { color: "#718096" } }, y: { beginAtZero: true, grid: { color: "#edf1f5" }, ticks: { color: "#8a98a9", precision: 0 } } } } }),
        new Chart(featurePanel.querySelector("#seats-chart"), { type: "doughnut", data: { labels: ["In use", "Available"], datasets: [{ data: [data.totals.seats_in_use, Math.max(data.totals.seat_count - data.totals.seats_in_use, 0)], backgroundColor: ["#1769d2", "#e7edf4"], borderWidth: 0, cutout: "72%" }] }, options: { ...common, plugins: { legend: { position: "bottom", labels: { color: "#718096", boxWidth: 9, font: { family: "DM Sans", size: 10 } } } } } }),
      ];
    } catch (error) { notify(error.message, "error"); }
  };
  await load();
  analyticsTimer = window.setInterval(load, 30000);
}

async function showStudy() {
  const dateValue = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const nextHour = new Date(Date.now() + 60 * 60000);
  nextHour.setMinutes(nextHour.getMinutes() < 30 ? 30 : 0, 0, 0);
  if (nextHour.getMinutes() === 0) nextHour.setHours(nextHour.getHours() + 1);
  const timeValue = `${String(nextHour.getHours()).padStart(2, "0")}:${String(nextHour.getMinutes()).padStart(2, "0")}`;
  const timeOptions = Array.from({ length: 26 }, (_, index) => {
    const minutes = 8 * 60 + index * 30;
    const hour = String(Math.floor(minutes / 60)).padStart(2, "0");
    const minute = String(minutes % 60).padStart(2, "0");
    return `<option value="${hour}:${minute}">${hour}:${minute}</option>`;
  }).join("");

  featurePanel.innerHTML = `${panelHeading("STUDY SPACES", "Find your focus", "Reserve a two-hour study session in a space that works for you. Check in within 15 minutes of start time to prevent auto-release.")}<div class="seat-controls"><label>Date<input id="seat-day" type="date" value="${dateValue}" min="${dateValue}"></label><label>Start time<select id="seat-slot">${timeOptions}</select></label><span class="seat-duration">2 hour session</span></div><div class="seat-layout"><section class="seat-map-panel"><div class="seat-map-header"><div><span class="eyebrow">NORTHSTAR LIBRARY · FLOOR 1</span><h2>Choose a seat</h2></div><div class="seat-legend"><span><i class="legend-available"></i>Available</span><span><i class="legend-occupied"></i>In use</span><span><i class="legend-selected"></i>Selected</span></div></div><div class="seat-map" id="seat-map" aria-live="polite"></div><div class="seat-map-foot"><span>WINDOW SIDE</span><span>MAIN AISLE</span><span>WINDOW SIDE</span></div><button class="button button-primary seat-confirm" id="seat-confirm" disabled>Choose an available seat</button></section><section class="reservation-side"><div class="subsection-heading"><div><span class="eyebrow">YOUR SCHEDULE</span><h2>Reservations</h2></div><button class="text-button" id="refresh-reservations">Refresh</button></div><div id="reservation-list" class="reservation-list"></div></section></div>`;
  featurePanel.querySelector("#seat-slot").value = timeValue;

  let selectedSeat = null;
  let bookable = false;

  const loadSeats = async () => {
    selectedSeat = null;
    const day = featurePanel.querySelector("#seat-day").value;
    const slot = featurePanel.querySelector("#seat-slot").value;
    const result = await api(`/api/seats?day=${encodeURIComponent(day)}&slot=${encodeURIComponent(slot)}`);
    bookable = result.bookable;
    const map = featurePanel.querySelector("#seat-map");
    const zones = [...new Set(result.seats.map((seat) => seat.zone))];
    map.innerHTML = zones.map((zone) => `<div class="seat-zone"><span class="seat-zone-label">${escapeHtml(zone)}</span><div class="seat-zone-grid">${result.seats.filter((seat) => seat.zone === zone).map((seat) => `<button type="button" class="seat-tile ${seat.status}" data-seat-id="${seat.id}" ${seat.status !== "available" || !bookable ? "disabled" : ""} aria-label="Seat ${escapeHtml(seat.label)}, ${escapeHtml(seat.status)}"><span class="seat-symbol">⌑</span><span>${escapeHtml(seat.label)}</span></button>`).join("")}</div></div>`).join("");
    featurePanel.querySelector("#seat-confirm").disabled = true;
    featurePanel.querySelector("#seat-confirm").textContent = userRole === "student" ? (bookable ? "Choose an available seat" : "Select a future time") : "Student booking only";
  };

  const loadReservations = async () => {
    const { reservations } = await api("/api/reservations");
    const list = featurePanel.querySelector("#reservation-list");
    const visible = reservations.filter((reservation) => ["booked", "checked_in"].includes(reservation.status));
    list.innerHTML = visible.length ? visible.map((reservation) => `<article class="reservation-item"><div class="reservation-seat"><span class="reservation-seat-icon">⌂</span><span><b>${escapeHtml(reservation.seat)} · ${escapeHtml(reservation.zone)}</b><small>${escapeHtml(reservation.starts_at)}</small>${userRole !== "student" ? `<small>${escapeHtml(reservation.member_name)}</small>` : ""}</span></div><span class="status-pill ${reservation.status === "checked_in" ? "status-active" : "status-pending"}">${reservation.status === "checked_in" ? "Checked in" : "Booked"}</span><div class="reservation-actions">${userRole === "student" && reservation.status === "booked" ? `<button class="table-action" data-check-in="${reservation.id}">Check in</button>` : ""}<button class="table-action danger-link" data-cancel-reservation="${reservation.id}">Cancel</button></div></article>`).join("") : '<div class="empty-state"><b>No upcoming reservations</b><p>Your booked spaces will appear here.</p></div>';
  };

  featurePanel.querySelector("#seat-map").addEventListener("click", (event) => {
    const seat = event.target.closest("[data-seat-id]");
    if (!seat || seat.disabled) return;
    featurePanel.querySelectorAll(".seat-tile.selected").forEach((item) => item.classList.remove("selected"));
    seat.classList.add("selected"); selectedSeat = Number(seat.dataset.seatId);
    const confirmButton = featurePanel.querySelector("#seat-confirm");
    confirmButton.disabled = false; confirmButton.textContent = `Reserve ${seat.querySelector("span:last-child").textContent} · 2 hours`;
  });

  featurePanel.querySelector("#seat-confirm").addEventListener("click", async () => {
    if (!selectedSeat || !bookable) return;
    const startsAt = `${featurePanel.querySelector("#seat-day").value} ${featurePanel.querySelector("#seat-slot").value}:00`;
    try { await api("/api/reservations", { method: "POST", body: JSON.stringify({ seat_id: selectedSeat, starts_at: startsAt }) }); notify("Your study seat is reserved."); await loadSeats(); await loadReservations(); }
    catch (error) { notify(error.message, "error"); }
  });

  featurePanel.querySelector("#seat-day").addEventListener("change", () => loadSeats().catch((error) => notify(error.message, "error")));
  featurePanel.querySelector("#seat-slot").addEventListener("change", () => loadSeats().catch((error) => notify(error.message, "error")));
  featurePanel.querySelector("#refresh-reservations").addEventListener("click", () => loadReservations().catch((error) => notify(error.message, "error")));

  featurePanel.querySelector("#reservation-list").addEventListener("click", async (event) => {
    const checkIn = event.target.closest("[data-check-in]");
    const cancel = event.target.closest("[data-cancel-reservation]");
    try {
      if (checkIn) await api(`/api/reservations/${checkIn.dataset.checkIn}/check-in`, { method: "POST", body: "{}" });
      if (cancel) await api(`/api/reservations/${cancel.dataset.cancelReservation}`, { method: "DELETE" });
      if (checkIn || cancel) { notify(checkIn ? "Checked in. Have a focused session." : "Reservation cancelled."); await loadReservations(); await loadSeats(); }
    } catch (error) { notify(error.message, "error"); }
  });

  await Promise.all([loadSeats(), loadReservations()]);
}

async function showQueue() {
  const canManage = userRole !== "student";
  featurePanel.innerHTML = `${panelHeading("DIGITAL WAITLIST", "Waiting queue", "Keep your place in line and get notified when a title is ready for checkout.")}${userRole === "student" ? '<div class="queue-join-row"><label>Unavailable title<select id="queue-book-select"><option value="">Choose a book</option></select></label><button class="button button-primary" id="queue-join">Join queue</button></div>' : ""}<div class="queue-list" id="queue-list"></div>`;

  const load = async () => {
    const { queue } = await api("/api/queue");
    const list = featurePanel.querySelector("#queue-list");
    list.innerHTML = queue.length ? queue.map((item) => `<article class="queue-row"><div class="queue-rank">${item.status === "waiting" ? String(item.position).padStart(2, "0") : "✓"}</div><div class="queue-book"><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.author)}${canManage ? ` · ${escapeHtml(item.member_name)}` : ""}</small></div><span class="status-pill ${item.status === "notified" ? "status-notified" : item.status === "waiting" ? "status-pending" : "status-inactive"}">${item.status === "notified" ? "Ready for pickup" : escapeHtml(item.status)}</span><small class="queue-date">${item.notified_at ? `Notified ${escapeHtml(item.notified_at)}` : `Joined ${escapeHtml(item.created_at)}`}</small><button class="table-action danger-link" data-leave-queue="${item.id}">${canManage ? "Remove" : "Leave queue"}</button></article>`).join("") : '<div class="empty-state"><span>≋</span><b>No waiting-list entries</b><p>Unavailable titles you join will appear here.</p></div>';
  };

  if (userRole === "student") {
    const { books } = await api("/api/books");
    const unavailable = books.filter((book) => book.available_copies === 0);
    featurePanel.querySelector("#queue-book-select").innerHTML = '<option value="">Choose a book</option>' + unavailable.map((book) => `<option value="${book.id}">${escapeHtml(book.title)} · ${escapeHtml(book.author)}</option>`).join("");
    featurePanel.querySelector("#queue-join").addEventListener("click", async () => {
      const bookId = Number(featurePanel.querySelector("#queue-book-select").value);
      if (!bookId) return notify("Choose an unavailable title first.", "error");
      try { await api("/api/queue", { method: "POST", body: JSON.stringify({ book_id: bookId }) }); notify("You joined the waiting queue."); await load(); }
      catch (error) { notify(error.message, "error"); }
    });
  }

  featurePanel.querySelector("#queue-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-leave-queue]");
    if (!button) return;
    try { await api(`/api/queue/${button.dataset.leaveQueue}`, { method: "DELETE" }); notify("Queue entry removed."); await load(); }
    catch (error) { notify(error.message, "error"); }
  });
  await load();
}

async function showLocator() {
  featurePanel.innerHTML = `${panelHeading("ON THE SHELF", "Book locator", "A clear route from catalog title to floor, shelf and rack.")}<div class="locator-toolbar"><label class="search-field"><span>⌕</span><input id="locator-search" type="search" placeholder="Search a title, author or ISBN"></label><label>Floor<select id="locator-floor"><option value="">All floors</option><option value="1">Floor 1</option><option value="2">Floor 2</option></select></label></div><div class="locator-layout"><div class="locator-map-wrap"><div class="locator-map-label"><span class="eyebrow">STACKS MAP</span><span>Click a shelf marker to filter matching titles</span></div><div class="locator-map" id="locator-map"></div></div><aside class="locator-details"><span class="eyebrow">MATCHING TITLES</span><h2 id="locator-result-title">All books</h2><div id="locator-results" class="locator-results"></div></aside></div>`;
  const { books } = await api("/api/books");
  const search = featurePanel.querySelector("#locator-search");
  const floor = featurePanel.querySelector("#locator-floor");
  const results = featurePanel.querySelector("#locator-results");
  const map = featurePanel.querySelector("#locator-map");

  const render = () => {
    const query = search.value.trim().toLowerCase();
    const level = floor.value;
    const filtered = books.filter((book) => (!level || book.floor === level) && (!query || `${book.title} ${book.author} ${book.isbn}`.toLowerCase().includes(query)));
    featurePanel.querySelector("#locator-result-title").textContent = query ? `${filtered.length} title${filtered.length === 1 ? "" : "s"} found` : level ? `Floor ${level}` : "All books";
    results.innerHTML = filtered.length ? filtered.map((book) => `<article class="locator-book"><span class="locator-pin">${escapeHtml(book.shelf)}</span><div><b>${escapeHtml(book.title)}</b><small>${escapeHtml(book.author)}</small><span>Floor ${escapeHtml(book.floor)} · Shelf ${escapeHtml(book.shelf)} · Rack ${escapeHtml(book.rack)}</span></div></article>`).join("") : '<p class="muted">No titles match this location or search.</p>';
    const locations = new Map();
    filtered.forEach((book) => {
      const key = `${book.floor}-${book.shelf}-${book.rack}`;
      if (!locations.has(key)) locations.set(key, []);
      locations.get(key).push(book);
    });
    map.innerHTML = locations.size ? [...locations.entries()].map(([key, titles]) => `<button class="locator-shelf" type="button" data-locator-key="${key}"><span class="shelf-marker">${escapeHtml(key.split("-")[1])}</span><span>Rack ${escapeHtml(key.split("-")[2])}</span><small>${titles.length} title${titles.length === 1 ? "" : "s"}</small></button>`).join("") : '<p class="muted">No shelf locations found.</p>';
  };

  search.addEventListener("input", render); floor.addEventListener("change", render);
  map.addEventListener("click", (event) => {
    const shelf = event.target.closest("[data-locator-key]");
    if (!shelf) return;
    const [bookFloor, bookShelf, rack] = shelf.dataset.locatorKey.split("-");
    floor.value = bookFloor;
    search.value = "";
    render();
    featurePanel.querySelector("#locator-results").scrollIntoView({ behavior: "smooth", block: "nearest" });
    featurePanel.querySelector("#locator-result-title").textContent = `Floor ${bookFloor} · Shelf ${bookShelf} · Rack ${rack}`;
  });
  render();
}

async function showAssistant() {
  featurePanel.innerHTML = `${panelHeading("AI ASSISTANT", "Library Assistant & Recommendations", "Ask questions about borrowing policies, fines and book availability, or explore personalized recommendations.")}<div class="assistant-layout"><section class="chat-panel"><div class="chat-header"><div><span class="eyebrow">SMART ASSISTANT</span><h2 style="font:700 14px Manrope,sans-serif;margin:4px 0 0;">Ask Northstar</h2></div><button class="text-button" id="clear-chat" type="button">Clear</button></div><div class="chat-messages" id="chat-messages"><div class="chat-msg bot">Hello! I am Northstar Library's assistant. Ask me about hours, borrowing limits, overdue fines (Rs. 5/day), study seats, or search for any book in our collection.</div></div><div class="chat-chips"><button class="chat-chip" type="button">What are library hours?</button><button class="chat-chip" type="button">How much is the overdue fine?</button><button class="chat-chip" type="button">How do study reservations work?</button><button class="chat-chip" type="button">Search for Clean Code</button></div><form class="chat-form" id="chat-form"><input id="chat-input" placeholder="Type your question..." autocomplete="off" required><button class="button button-primary" type="submit">Ask <span>→</span></button></form></section><section class="recommendations-panel"><div class="subsection-heading"><div><span class="eyebrow">CURATED FOR YOU</span><h2 style="font:700 14px Manrope,sans-serif;margin:4px 0 0;">Book recommendations</h2></div></div><p class="muted" style="font-size:10px;margin:6px 0 10px;">Select your reading interests to tune recommendations:</p><div class="pref-chips" id="pref-chips"></div><button class="button button-quiet" id="save-prefs" type="button" style="width:100%;font-size:10px;margin-bottom:14px;">Save interests & refresh</button><div class="rec-list" id="rec-list"></div></section></div>`;

  const messages = featurePanel.querySelector("#chat-messages");
  const form = featurePanel.querySelector("#chat-form");
  const input = featurePanel.querySelector("#chat-input");
  const chipContainer = featurePanel.querySelector(".chat-chips");

  const sendQuestion = async (text) => {
    if (!text.trim()) return;
    const userMsg = document.createElement("div");
    userMsg.className = "chat-msg user";
    userMsg.textContent = text;
    messages.append(userMsg);
    messages.scrollTop = messages.scrollHeight;

    const botMsg = document.createElement("div");
    botMsg.className = "chat-msg bot";
    botMsg.textContent = "Thinking...";
    messages.append(botMsg);
    messages.scrollTop = messages.scrollHeight;

    try {
      const res = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text }) });
      botMsg.textContent = res.answer;
    } catch (error) {
      botMsg.textContent = "Sorry, I could not complete your request: " + error.message;
    }
    messages.scrollTop = messages.scrollHeight;
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = "";
    sendQuestion(text);
  });

  chipContainer.addEventListener("click", (e) => {
    const chip = e.target.closest(".chat-chip");
    if (chip) sendQuestion(chip.textContent);
  });

  featurePanel.querySelector("#clear-chat").addEventListener("click", () => {
    messages.innerHTML = '<div class="chat-msg bot">Conversation cleared. What can I help you with?</div>';
  });

  // Recommendations and preferences
  const prefContainer = featurePanel.querySelector("#pref-chips");
  const recList = featurePanel.querySelector("#rec-list");
  const availableCats = ["Computer Science", "Fiction", "History", "Personal Growth", "Philosophy", "Business", "Psychology", "Design", "Science", "Arts", "Travel", "Memoir"];

  const loadRecommendations = async () => {
    try {
      const res = await api("/api/recommendations");
      const currentPrefs = res.preferences || [];
      prefContainer.innerHTML = availableCats.map((cat) => `<button type="button" class="pref-chip ${currentPrefs.includes(cat) ? "selected" : ""}" data-category="${escapeHtml(cat)}">${escapeHtml(cat)}</button>`).join("");
      recList.innerHTML = res.recommendations.length ? res.recommendations.map((book) => `<article class="rec-item"><div class="rec-item-info"><b>${escapeHtml(book.title)}</b><small>${escapeHtml(book.author)} · ${escapeHtml(book.category)}</small><p>${escapeHtml(book.reason || "Recommended based on your reading.")}</p><div style="margin-top:6px;"><a href="#locator" class="table-action" style="font-size:9px;">Locate on shelf →</a></div></div></article>`).join("") : '<p class="muted">No recommendations available right now.</p>';
    } catch (error) { recList.innerHTML = `<p class="muted">${error.message}</p>`; }
  };

  prefContainer.addEventListener("click", (e) => {
    const chip = e.target.closest(".pref-chip");
    if (chip) chip.classList.toggle("selected");
  });

  featurePanel.querySelector("#save-prefs").addEventListener("click", async () => {
    const selected = Array.from(prefContainer.querySelectorAll(".pref-chip.selected")).map((c) => c.dataset.category);
    try {
      if (userRole === "student") {
        await api("/api/preferences", { method: "POST", body: JSON.stringify({ categories: selected }) });
      }
      notify("Reading interests saved.");
      await loadRecommendations();
    } catch (error) { notify(error.message, "error"); }
  });

  await loadRecommendations();
}

let activeStream = null;

async function showScanner() {
  featurePanel.innerHTML = `${panelHeading("SMART SCANNER", "Smart book scanner & ISBN reader", "Scan an ISBN or QR code using your camera or enter manually to view book details and circulation options.")}<div class="scanner-layout"><section class="scanner-card"><div class="scanner-controls"><button class="button button-primary" id="start-cam-btn" type="button">Start camera</button><button class="button button-quiet" id="stop-cam-btn" type="button" disabled>Stop camera</button></div><div class="scanner-viewport" id="scanner-viewport"><video id="scanner-video" playsinline muted autoplay></video><div class="scanner-reticle"></div><span id="scanner-status" style="position:absolute;bottom:10px;font-size:10px;color:#a8c2de;background:rgba(0,0,0,0.6);padding:4px 8px;border-radius:4px;">Camera is off. Click 'Start camera' or use manual scan below.</span></div><div class="scanner-input-row"><input id="manual-scan-input" placeholder="Enter or paste ISBN or QR code (e.g. 9780132350884)" autocomplete="off"><button class="button button-primary" id="manual-scan-btn" type="button">Look up</button></div><div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;"><span style="font-size:9px;color:#7e8ea2;align-self:center;">Try sample ISBN:</span><button class="chat-chip" type="button" data-sample="9780132350884">Clean Code</button><button class="chat-chip" type="button" data-sample="9780735211292">Atomic Habits</button><button class="chat-chip" type="button" data-sample="9780062316097">Sapiens</button></div></section><section class="scanner-card"><div class="subsection-heading"><div><span class="eyebrow">BOOK DETAILS</span><h2 style="font:700 14px Manrope,sans-serif;margin:4px 0 0;">Scan result</h2></div></div><div id="scan-result-container"><div class="empty-state" style="padding:28px 14px;"><span>▦</span><b>No book scanned yet</b><p>Align a barcode/QR in camera or enter ISBN.</p></div></div></section></div>`;

  const video = featurePanel.querySelector("#scanner-video");
  const status = featurePanel.querySelector("#scanner-status");
  const startBtn = featurePanel.querySelector("#start-cam-btn");
  const stopBtn = featurePanel.querySelector("#stop-cam-btn");
  const manualInput = featurePanel.querySelector("#manual-scan-input");
  const manualBtn = featurePanel.querySelector("#manual-scan-btn");
  const resultContainer = featurePanel.querySelector("#scan-result-container");

  const lookupBook = async (rawCode) => {
    let clean = String(rawCode || "").trim().replace("-", "");
    if (clean.startsWith("BOOK:")) clean = clean.slice(5).trim();
    if (!clean) return;
    resultContainer.innerHTML = '<p class="muted" style="padding:14px;">Looking up catalog record...</p>';
    try {
      const res = await api(`/api/books?q=${encodeURIComponent(clean)}`);
      const book = res.books.find((b) => b.isbn === clean || clean.includes(b.isbn)) || res.books[0];
      if (!book) {
        resultContainer.innerHTML = `<div class="scan-result-card" style="border-color:#f5c6cb;background:#fff5f6;"><h3>Not found</h3><p style="font-size:10px;color:#721c24;margin:0;">No book matched code: <b>${escapeHtml(clean)}</b></p></div>`;
        return;
      }
      resultContainer.innerHTML = `<div class="scan-result-card"><h3>${escapeHtml(book.title)}</h3><p style="font-size:10px;color:#617188;margin:2px 0 6px;">by ${escapeHtml(book.author)} · ${escapeHtml(book.category)}</p><div style="font-size:10px;margin:6px 0;"><span class="status-pill ${book.available_copies > 0 ? "status-active" : "status-inactive"}">${book.available_copies > 0 ? `${book.available_copies} of ${book.total_copies} available` : "All copies on loan"}</span></div><p style="font-size:10px;color:#7a8a9e;margin:6px 0;">ISBN: <b>${escapeHtml(book.isbn)}</b><br>Location: Floor ${escapeHtml(book.floor)}, Shelf ${escapeHtml(book.shelf)}, Rack ${escapeHtml(book.rack)}</p><p style="font-size:10px;line-height:1.4;margin:8px 0;">${escapeHtml(book.description || "A Northstar University Library catalog title.")}</p><div style="display:flex;gap:8px;margin-top:12px;">${["admin", "staff"].includes(userRole) ? `<button class="button button-primary" id="scan-circ-issue" type="button" style="font-size:9px;height:32px;padding:0 12px;">Check out title</button><button class="button button-quiet" id="scan-circ-return" type="button" style="font-size:9px;height:32px;padding:0 12px;">Check in title</button>` : `<a href="#locator" class="button button-primary" style="font-size:9px;height:32px;padding:0 12px;display:inline-flex;align-items:center;">Locate on shelf</a>`}</div></div>`;

      resultContainer.querySelector("#scan-circ-issue")?.addEventListener("click", () => {
        openFeature("circulation").then(() => {
          const isbnInput = document.querySelector("#circ-isbn");
          if (isbnInput) { isbnInput.value = book.isbn; isbnInput.focus(); }
        });
      });
      resultContainer.querySelector("#scan-circ-return")?.addEventListener("click", () => {
        openFeature("circulation").then(() => {
          document.querySelector('[data-circulation-mode="return"]')?.click();
          const isbnInput = document.querySelector("#circ-isbn");
          if (isbnInput) { isbnInput.value = book.isbn; isbnInput.focus(); }
        });
      });
    } catch (error) { resultContainer.innerHTML = `<p class="muted">${error.message}</p>`; }
  };

  const stopCamera = () => {
    if (activeStream) {
      activeStream.getTracks().forEach((t) => t.stop());
      activeStream = null;
    }
    video.srcObject = null;
    startBtn.disabled = false;
    stopBtn.disabled = true;
    status.textContent = "Camera stopped.";
  };

  startBtn.addEventListener("click", async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      activeStream = stream;
      video.srcObject = stream;
      startBtn.disabled = true;
      stopBtn.disabled = false;
      status.textContent = "Scanning... Hold ISBN or QR code in the reticle.";

      // Use BarcodeDetector if supported
      if ("BarcodeDetector" in window) {
        const detector = new window.BarcodeDetector({ formats: ["ean_13", "ean_8", "qr_code", "code_128"] });
        const scanLoop = async () => {
          if (!activeStream) return;
          try {
            const barcodes = await detector.detect(video);
            if (barcodes.length) {
              const code = barcodes[0].rawValue;
              notify(`Scanned: ${code}`);
              stopCamera();
              lookupBook(code);
              return;
            }
          } catch (_) {}
          requestAnimationFrame(scanLoop);
        };
        requestAnimationFrame(scanLoop);
      }
    } catch (err) {
      status.textContent = "Camera access error: " + err.message + ". Use manual input below.";
    }
  });

  stopBtn.addEventListener("click", stopCamera);

  manualBtn.addEventListener("click", () => {
    lookupBook(manualInput.value);
  });

  manualInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") lookupBook(manualInput.value);
  });

  featurePanel.querySelectorAll("[data-sample]").forEach((btn) => {
    btn.addEventListener("click", () => {
      manualInput.value = btn.dataset.sample;
      lookupBook(btn.dataset.sample);
    });
  });
}

let activeSpeech = null;

async function showAudio() {
  featurePanel.innerHTML = `${panelHeading("LISTEN & LEARN", "Audio library", "Listen to narrated book introductions and summaries with native text-to-speech.")}<div class="audio-layout"><section class="audio-card"><div class="audio-player"><div class="audio-player-meta"><span class="eyebrow" style="color:#a7c8ed;">NOW PLAYING</span><b id="audio-title">Select a title to listen</b><small id="audio-author">Northstar University Library</small></div><div class="audio-text-display" id="audio-text">Click any title on the right to start listening. Use the controls below to play, pause, or change playback speed.</div><div class="audio-controls-row"><button class="button button-white" id="audio-play-btn" type="button">▶ Play</button><button class="button button-quiet" id="audio-pause-btn" type="button" disabled>⏸ Pause</button><button class="button button-quiet" id="audio-stop-btn" type="button" disabled>⏹ Stop</button><label style="font-size:9px;display:flex;align-items:center;gap:4px;margin-left:auto;color:#d0e2f5;">Speed:<select id="audio-rate" style="background:#0e3666;color:white;border:1px solid #235896;border-radius:3px;padding:3px 6px;font-size:9px;"><option value="0.85">0.85x</option><option value="1" selected>1.0x</option><option value="1.2">1.2x</option><option value="1.4">1.4x</option></select></label></div></div></section><section class="audio-card"><div class="subsection-heading"><div><span class="eyebrow">CATALOG OVERVIEWS</span><h2 style="font:700 14px Manrope,sans-serif;margin:4px 0 0;">Available audio titles</h2></div></div><div class="audio-book-list" id="audio-book-list"></div></section></div>`;

  const titleEl = featurePanel.querySelector("#audio-title");
  const authorEl = featurePanel.querySelector("#audio-author");
  const textEl = featurePanel.querySelector("#audio-text");
  const playBtn = featurePanel.querySelector("#audio-play-btn");
  const pauseBtn = featurePanel.querySelector("#audio-pause-btn");
  const stopBtn = featurePanel.querySelector("#audio-stop-btn");
  const rateSelect = featurePanel.querySelector("#audio-rate");
  const bookList = featurePanel.querySelector("#audio-book-list");

  let currentBook = null;

  const stopAudio = () => {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    playBtn.textContent = "▶ Play";
    playBtn.disabled = !currentBook;
    pauseBtn.disabled = true;
    stopBtn.disabled = true;
  };

  const playAudio = () => {
    if (!currentBook || !("speechSynthesis" in window)) {
      if (!("speechSynthesis" in window)) notify("Speech synthesis is not supported in this browser.", "error");
      return;
    }
    window.speechSynthesis.cancel();
    const narration = `${currentBook.title}, by ${currentBook.author}. In the category of ${currentBook.category}. ${currentBook.description || "An insightful title available at Northstar University Library."} Located on Floor ${currentBook.floor}, shelf ${currentBook.shelf}.`;
    const utterance = new SpeechSynthesisUtterance(narration);
    utterance.rate = Number(rateSelect.value) || 1.0;
    utterance.onend = () => {
      stopAudio();
    };
    utterance.onerror = () => {
      stopAudio();
    };
    window.speechSynthesis.speak(utterance);
    playBtn.textContent = "▶ Playing";
    playBtn.disabled = true;
    pauseBtn.disabled = false;
    stopBtn.disabled = false;
  };

  playBtn.addEventListener("click", playAudio);
  pauseBtn.addEventListener("click", () => {
    if ("speechSynthesis" in window) {
      if (window.speechSynthesis.paused) {
        window.speechSynthesis.resume();
        pauseBtn.textContent = "⏸ Pause";
      } else {
        window.speechSynthesis.pause();
        pauseBtn.textContent = "▶ Resume";
      }
    }
  });
  stopBtn.addEventListener("click", stopAudio);
  rateSelect.addEventListener("change", () => {
    if (playBtn.disabled && !pauseBtn.disabled) {
      playAudio();
    }
  });

  const { books } = await api("/api/books");
  bookList.innerHTML = books.map((b) => `<div class="audio-book-item" data-audio-id="${b.id}"><b>${escapeHtml(b.title)}</b><small>${escapeHtml(b.author)} · ${escapeHtml(b.category)}</small></div>`).join("");

  bookList.addEventListener("click", (e) => {
    const item = e.target.closest(".audio-book-item");
    if (!item) return;
    bookList.querySelectorAll(".audio-book-item").forEach((el) => el.classList.remove("active"));
    item.classList.add("active");
    currentBook = books.find((b) => b.id === Number(item.dataset.audioId));
    if (currentBook) {
      stopAudio();
      titleEl.textContent = currentBook.title;
      authorEl.textContent = `${currentBook.author} · ${currentBook.category}`;
      textEl.textContent = `"${currentBook.title}" by ${currentBook.author}. ${currentBook.description || "A featured title in the Northstar University Library collection."} Located on Floor ${currentBook.floor}, Shelf ${currentBook.shelf}, Rack ${currentBook.rack}.`;
      playAudio();
    }
  });
}

function showOverview() {
  if (featurePanel) featurePanel.hidden = true;
  document.querySelectorAll(".page-content > *:not(#feature-panel)").forEach((element) => {
    element.hidden = false;
  });
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", link.getAttribute("href") === "/dashboard");
  });
  const breadcrumb = document.querySelector("#breadcrumb-current");
  if (breadcrumb) breadcrumb.textContent = "Overview";
  window.history.replaceState(null, "", "/dashboard");
}

async function openFeature(view) {
  if (view !== "analytics") window.clearInterval(analyticsTimer);
  if (activeStream) {
    activeStream.getTracks().forEach((t) => t.stop());
    activeStream = null;
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();

  if (!view || view === "overview") {
    showOverview();
    return;
  }

  featurePanel.hidden = false;
  document.querySelectorAll(".page-content > *:not(#feature-panel)").forEach((element) => { element.hidden = true; });
  document.querySelectorAll(".nav-link").forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${view}`));

  const breadcrumb = document.querySelector("#breadcrumb-current");
  const titles = {
    catalog: "Discover books",
    "my-books": "My books",
    circulation: "Circulation",
    members: "Members",
    analytics: "Analytics",
    study: "Study spaces",
    queue: "Waiting queue",
    locator: "Book locator",
    scanner: "Smart scanner",
    assistant: "AI assistant",
    audio: "Listen & learn",
  };
  if (breadcrumb) breadcrumb.textContent = titles[view] || view;

  if (view === "catalog") return showCatalog();
  if (view === "members" && ["admin", "staff"].includes(userRole)) return showMembers();
  if (view === "circulation" && ["admin", "staff"].includes(userRole)) return showCirculation();
  if (view === "my-books" && userRole === "student") return showMyBooks();
  if (view === "analytics" && userRole === "admin") return showAnalytics();
  if (view === "study") return showStudy();
  if (view === "queue") return showQueue();
  if (view === "locator") return showLocator();
  if (view === "scanner") return showScanner();
  if (view === "assistant") return showAssistant();
  if (view === "audio") return showAudio();

  featurePanel.innerHTML = `${panelHeading("SMART LIBRARY", titles[view] || view, "Workspace view.")}<div class="empty-state"><b>Feature loaded</b></div>`;
}

// Notification Bell Support
function initNotifications() {
  const btn = document.querySelector("#notification-button");
  const badge = document.querySelector("#notification-badge");
  const dropdown = document.querySelector("#notification-dropdown");
  const list = document.querySelector("#notification-dropdown-list");
  const markAllBtn = document.querySelector("#mark-all-notifications-read");

  if (!btn || !dropdown) return;

  const updateNotifications = async () => {
    try {
      const res = await api("/api/notifications");
      if (res.unread > 0) {
        badge.hidden = false;
      } else {
        badge.hidden = true;
      }
      list.innerHTML = res.notifications.length ? res.notifications.map((n) => `<div class="notification-item ${n.read_at ? "" : "unread"}" data-notif-id="${n.id}"><b>${escapeHtml(n.kind === "queue" ? "Waitlist Update" : n.kind === "due" ? "Due Date Reminder" : "Notice")}</b><span>${escapeHtml(n.message)}</span><br><small>${escapeHtml(n.created_at)}</small></div>`).join("") : '<p class="muted" style="padding:14px;font-size:11px;">No notifications yet.</p>';
    } catch (_) {}
  };

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    dropdown.hidden = !dropdown.hidden;
    if (!dropdown.hidden) updateNotifications();
  });

  dropdown.addEventListener("click", async (e) => {
    const item = e.target.closest("[data-notif-id]");
    if (item && item.classList.contains("unread")) {
      const id = item.dataset.notifId;
      try {
        await api(`/api/notifications/${id}/read`, { method: "POST", body: "{}" });
        item.classList.remove("unread");
        updateNotifications();
      } catch (_) {}
    }
  });

  markAllBtn?.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      await api("/api/notifications/read-all", { method: "POST", body: "{}" });
      notify("All notifications marked as read.");
      updateNotifications();
    } catch (_) {}
  });

  document.addEventListener("click", (e) => {
    if (!dropdown.hidden && !dropdown.contains(e.target) && e.target !== btn) {
      dropdown.hidden = true;
    }
  });

  updateNotifications();
  window.setInterval(updateNotifications, 45000);
}

// Global Event Wiring: Overview, Hash navigation, and Links
document.addEventListener("DOMContentLoaded", () => {
  initNotifications();

  // Handle all links with href^="#" anywhere on the page
  document.body.addEventListener("click", (event) => {
    const anchor = event.target.closest('a[href^="#"]');
    if (anchor) {
      event.preventDefault();
      const view = anchor.getAttribute("href").slice(1);
      window.history.replaceState(null, "", `#${view}`);
      openFeature(view);
      return;
    }

    const overviewLink = event.target.closest('a[href="/dashboard"], a.brand');
    if (overviewLink) {
      event.preventDefault();
      showOverview();
    }
  });

  window.addEventListener("hashchange", () => {
    const hash = window.location.hash.slice(1);
    if (hash) {
      openFeature(hash);
    } else {
      showOverview();
    }
  });

  if (window.location.hash) {
    openFeature(window.location.hash.slice(1));
  }
});
