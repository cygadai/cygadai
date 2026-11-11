const messagesEl = document.getElementById("messages");
const form = document.getElementById("chatForm");
const promptEl = document.getElementById("prompt");
const sendBtn = document.getElementById("sendBtn");
const providerEl = document.getElementById("provider");
const clearBtn = document.getElementById("clearBtn");
const installBtn = document.getElementById("installBtn");

let sessionId = localStorage.getItem("cygad_session") || crypto.randomUUID();
localStorage.setItem("cygad_session", sessionId);
let deferredInstall = null;
let appPassword = sessionStorage.getItem("cygad_password") || "";

function addMessage(role, text, meta="") {
  const welcome = messagesEl.querySelector(".welcome");
  if (welcome) welcome.remove();
  const item = document.createElement("div");
  item.className = `message ${role}`;
  item.textContent = text;
  if (meta) {
    const label = document.createElement("div");
    label.className = "meta";
    label.textContent = meta;
    item.appendChild(label);
  }
  messagesEl.appendChild(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function sendMessage(message) {
  if (!message.trim()) return;
  addMessage("user", message);
  promptEl.value = "";
  sendBtn.disabled = true;
  sendBtn.textContent = "Thinking…";
  try {
    const headers = {"Content-Type":"application/json"};
    if (appPassword) headers["X-App-Password"] = appPassword;
    let response = await fetch("/api/chat", {
      method:"POST", headers,
      body:JSON.stringify({message, session_id:sessionId, provider:providerEl.value})
    });
    if (response.status === 401 && !appPassword) {
      appPassword = window.prompt("Enter the CYGAD AI app password:");
      if (!appPassword) throw new Error("Password is required.");
      sessionStorage.setItem("cygad_password", appPassword);
      headers["X-App-Password"] = appPassword;
      response = await fetch("/api/chat", {
        method:"POST", headers,
        body:JSON.stringify({message, session_id:sessionId, provider:providerEl.value})
      });
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Request failed.");
    addMessage("assistant", data.answer, `Answered by ${data.provider}`);
  } catch (err) {
    addMessage("assistant", `Sorry, I could not answer: ${err.message}`);
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "Send ↑";
    promptEl.focus();
  }
}

form.addEventListener("submit", e => {
  e.preventDefault();
  sendMessage(promptEl.value);
});
promptEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});
messagesEl.addEventListener("click", e => {
  if (e.target.classList.contains("suggestion")) sendMessage(e.target.textContent);
});
clearBtn.addEventListener("click", async () => {
  if (!confirm("Clear this conversation's saved history?")) return;
  const headers = {};
  if (appPassword) headers["X-App-Password"] = appPassword;
  const response = await fetch("/api/clear", {
    method:"POST", headers:{"Content-Type":"application/json", ...headers},
    body:JSON.stringify({session_id:sessionId})
  });
  if (response.ok) {
    messagesEl.innerHTML = '<div class="welcome"><div class="orb">✦</div><h2>New conversation</h2><p>What are we building today?</p></div>';
  } else {
    alert("Could not clear the conversation.");
  }
});
window.addEventListener("beforeinstallprompt", e => {
  e.preventDefault(); deferredInstall = e; installBtn.hidden = false;
});
installBtn.addEventListener("click", async () => {
  if (!deferredInstall) return;
  deferredInstall.prompt();
  await deferredInstall.userChoice;
  deferredInstall = null;
  installBtn.hidden = true;
});
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(()=>{}));
}
