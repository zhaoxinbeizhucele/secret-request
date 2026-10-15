import { encryptSecret } from "./crypto.js";

const $ = (id) => document.getElementById(id);
const requestId = location.pathname.split("/")[2];
const token = location.hash.slice(1);
let current, busy = false, pendingEnvelope, countdown = 0, rendered = false, attemptedSubmission = false, attemptedDecline = false, finished = false;
const fieldInputs = new Map();
const states = {
  pending: "请确认请求用途，再决定是否提供机密。",
  submitted: "已提交，等待发起程序领取。",
  consumed: "已交付给发起程序，本次请求结束。",
  declined: "你已拒绝这次请求。",
  cancelled: "发起程序已取消请求。",
  expired: "请求已过期，请让 Agent 重新申请。"
};

function clearInput() {
  $("secret").value = ""; $("multiline-secret").value = "";
  for (const input of fieldInputs.values()) input.value = "";
}
function renderFields(fields) {
  if (rendered) return;
  rendered = true;
  $("legacy-field").hidden = Boolean(fields);
  if (!fields) return;
  for (const field of fields) {
    const group = document.createElement("div"); group.className = "field";
    const label = document.createElement("label");
    const input = document.createElement(field.type === "textarea" ? "textarea" : "input");
    input.id = "field-" + field.id;
    label.htmlFor = input.id;
    label.textContent = field.label + (field.required ? "" : "（选填）") + (field.type === "textarea" ? "（明文显示）" : "");
    input.autocomplete = "off"; input.autocapitalize = "off"; input.spellcheck = false;
    input.maxLength = 65536; input.required = field.required;
    input.setAttribute("aria-describedby", "hint");
    if (field.type === "textarea") input.rows = 5;
    else input.type = field.type;
    group.append(label);
    const wrap = document.createElement("div"); wrap.className = "input-wrap"; wrap.append(input);
    if (field.type === "password") {
      const toggle = document.createElement("button");
      toggle.type = "button"; toggle.className = "quiet"; toggle.textContent = "显示";
      toggle.setAttribute("aria-label", "显示" + field.label); toggle.setAttribute("aria-pressed", "false");
      toggle.onclick = () => {
        const show = input.type === "password";
        input.type = show ? "text" : "password"; toggle.textContent = show ? "隐藏" : "显示";
        toggle.setAttribute("aria-pressed", String(show));
        toggle.setAttribute("aria-label", toggle.textContent + field.label);
      };
      wrap.append(toggle);
    }
    group.append(wrap); $("fields").append(group); fieldInputs.set(field.id, input);
  }
}
function finish(status, hint) {
  if (finished) return;
  finished = true; clearInput(); pendingEnvelope = undefined;
  $("form").hidden = true; $("error").hidden = true;
  $("status").textContent = status;
  $("close-hint").textContent = hint + "若浏览器未自动关闭，请关闭此标签页。";
  $("close-hint").hidden = false;
  window.close();
}
function submitted() { finish("已提交，等待发起程序取回。", "已提交并清空输入。"); }
function declined() { finish(states.declined, "已拒绝并清空输入，未提供机密。"); }
function setBusy(value, action = "submit") {
  busy = value;
  for (const input of $("form").querySelectorAll("input,textarea,button")) input.disabled = value;
  $("submit").textContent = value && action === "submit" ? "正在提交…" : "提交本次机密";
  $("decline").textContent = value && action === "decline" ? "正在拒绝…" : "拒绝请求";
}
function error(message) { $("error").textContent = message; $("error").hidden = false; }
async function api(action = "", body) {
  const deadline = AbortSignal.timeout(12000);
  const response = await fetch(`/api/requests/${encodeURIComponent(requestId)}${action}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store", redirect: "error",
    signal: deadline,
    headers: { Authorization: "Bearer " + token, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}
async function refresh() {
  if (finished) return;
  try {
    current = await api();
    if (finished) return;
    countdown = performance.now() + current.remaining_seconds * 1000;
    $("title").textContent = current.name;
    $("agent").textContent = (current.agent || "未注明 Agent") + "（自行声明）";
    $("created").textContent = current.created_at ? new Date(current.created_at).toLocaleString("zh-CN", {hour12: false}) : "未记录";
    $("purpose").textContent = current.purpose;
    $("request").hidden = false;
    $("status").textContent = states[current.state] || "请求不可用。";
    $("form").hidden = current.state !== "pending";
    renderFields(current.fields);
    if (attemptedSubmission && ["submitted", "consumed"].includes(current.state)) { submitted(); return; }
    if (attemptedDecline && current.state === "declined") { declined(); return; }
    if (current.state !== "pending") { clearInput(); pendingEnvelope = undefined; }
    tick();
  } catch (failure) {
    if (failure.message === "404") {
      clearInput(); pendingEnvelope = undefined;
      $("form").hidden = true;
      $("status").textContent = "请求不存在或入口已失效，请让 Agent 重新申请。";
    } else {
      $("status").textContent = "暂时无法连接服务，正在重试。请检查网络连接。";
    }
  }
}
function tick() {
  if (!current || finished) return;
  const seconds = Math.max(0, Math.ceil((countdown - performance.now()) / 1000));
  $("remaining").textContent = `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
  if (!seconds && current.state === "pending") {
    clearInput(); pendingEnvelope = undefined; $("form").hidden = true;
    $("status").textContent = states.expired;
  }
}
$("visibility").onclick = () => {
  const show = $("secret").type === "password";
  $("secret").type = show ? "text" : "password";
  $("visibility").textContent = show ? "隐藏" : "显示";
  $("visibility").setAttribute("aria-pressed", String(show));
};
$("multiline").onchange = () => {
  const multi = $("multiline").checked;
  const from = multi ? $("secret") : $("multiline-secret");
  const to = multi ? $("multiline-secret") : $("secret");
  if (!multi && /[\r\n]/.test(from.value)) {
    $("multiline").checked = true;
    error("内容包含换行，请保留多行模式，以免改变机密内容。");
    return;
  }
  to.value = from.value; from.value = "";
  $("multiline-secret").hidden = !multi;
  $("secret").parentElement.hidden = multi;
  $("secret-label").htmlFor = multi ? "multiline-secret" : "secret";
  to.focus();
};
$("form").onsubmit = async (event) => {
  event.preventDefault();
  if (busy || current?.state !== "pending") return;
  if (pendingEnvelope && ($("secret").value || $("multiline-secret").value || [...fieldInputs.values()].some(input => input.value))) {
    error("上次提交仍待确认。请先清空新输入再重试，或拒绝本次请求后重新申请。");
    return;
  }
  $("error").hidden = true;
  let value;
  if (current.fields) {
    if (!pendingEnvelope) {
      for (const input of fieldInputs.values()) if (!input.reportValidity()) return;
      value = JSON.stringify(Object.fromEntries([...fieldInputs].map(([id, input]) => [id, input.value])));
    }
  } else value = $("multiline").checked ? $("multiline-secret").value : $("secret").value;
  if (!pendingEnvelope && !value) { error("请输入本次要提供的机密，或选择拒绝请求。"); return; }
  setBusy(true);
  try {
    pendingEnvelope ||= await encryptSecret(value, current.public_key, requestId);
    clearInput();
    attemptedSubmission = true;
    await api("/submit", pendingEnvelope);
    submitted();
  } catch (failure) {
    if (failure.message === "size") error("内容不能为空、不能包含空字符，且不能超过 64 KiB。");
    else if (failure.message === "409" || failure.message === "404") { await refresh(); }
    else error("提交尚未确认。可以再次点击提交，或检查网络连接后重试。");
  } finally { setBusy(false); }
};
$("decline").onclick = async () => {
  if (busy || finished || current?.state !== "pending") return;
  setBusy(true, "decline");
  attemptedDecline = true;
  try { await api("/decline", {}); declined(); }
  catch {
    await refresh();
    if (!finished) error("拒绝尚未确认，请检查连接后重试。");
  }
  finally { setBusy(false); }
};
if (!requestId || !token) {
  $("status").textContent = "请从本次申请的通知链接打开输入页。";
} else if (!crypto.subtle) {
  $("status").textContent = "此页面需要安全的 HTTPS 连接，请使用通知中的原始地址。";
} else {
  await refresh();
  setInterval(() => { if (!busy) refresh(); }, 2000);
  setInterval(tick, 1000);
}
addEventListener("pagehide", clearInput);
