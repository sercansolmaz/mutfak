// Theme toggle: remembers the choice in a cookie so the server renders it without a flash.
document.querySelectorAll(".theme-toggle").forEach((btn) => {
  btn.addEventListener("click", () => {
    const root = document.documentElement;
    const current = root.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    document.cookie = `tema=${next}; path=/; max-age=31536000; SameSite=Lax; Secure`;
  });
});

// Voting without a page reload. Works as a plain form post when JavaScript is off.
const toast = document.querySelector(".toast");
let toastTimer;
function showToast(text) {
  if (!toast) return;
  toast.textContent = text;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.hidden = true), 4000);
}

document.querySelectorAll(".vote-form").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const ticket = form.closest(".ticket");
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      const resp = await fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch" },
        credentials: "same-origin",
      });
      const data = await resp.json();
      if (data.error) {
        showToast(data.error);
        return;
      }
      ticket.classList.toggle("is-voted", data.voted);
      ticket.classList.toggle("just-voted", data.voted);
      button.setAttribute("aria-pressed", String(data.voted));
      ticket.querySelector("[data-count]").textContent = `${data.count} oy`;
    } catch {
      showToast("Oy kaydedilemedi. Bağlantınızı kontrol edip tekrar deneyin.");
    } finally {
      button.disabled = false;
    }
  });
});
