(() => {
  const token = document.querySelector("#app-csrf [name=csrfmiddlewaretoken]")?.value;
  if (!token) return;
  const host = document.createElement("div");
  host.className = "actionable-notifications";
  host.setAttribute("aria-live", "polite");
  document.body.append(host);
  const seen = new Set();

  function button(label, className, callback) {
    const element = document.createElement("button");
    element.type = "button";
    element.className = className;
    element.textContent = label;
    element.addEventListener("click", callback);
    return element;
  }

  async function post(url, data = {}) {
    const body = new URLSearchParams({ csrfmiddlewaretoken: token, ...data });
    const response = await fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": token, "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The notification action failed.");
    return result;
  }

  function render(item) {
    if (seen.has(item.id)) return;
    seen.add(item.id);
    const card = document.createElement("section");
    card.className = "actionable-notification";
    const close = button("×", "notification-close", async () => {
      try {
        await post(`/notifications/${item.id}/dismiss/`);
        card.remove();
      } catch (error) {
        console.error(error);
      }
    });
    const kind = document.createElement("span");
    kind.textContent = item.kind;
    const title = document.createElement("strong");
    title.textContent = item.title;
    const duration = document.createElement("select");
    duration.setAttribute("aria-label", "Extend task by");
    [["15", "15 minutes"], ["30", "30 minutes"], ["60", "1 hour"], ["120", "2 hours"],
      ["tomorrow", "Tomorrow"], ["custom", "Custom duration"]].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      duration.append(option);
    });
    const custom = document.createElement("input");
    custom.type = "number";
    custom.min = "1";
    custom.max = "1440";
    custom.placeholder = "Minutes";
    custom.setAttribute("aria-label", "Custom extension minutes");
    custom.hidden = true;
    duration.addEventListener("change", () => { custom.hidden = duration.value !== "custom"; });
    const actions = document.createElement("div");
    actions.className = "notification-actions";
    const action = async (name, data = {}) => {
      try {
        await post(`/notifications/${item.id}/${name}/`, data);
        card.remove();
      } catch (error) {
        window.alert(error.message);
      }
    };
    actions.append(
      button("Mark done", "notification-done", () => action("done")),
      button("Extend task", "notification-extend", () => action("extend", {
        option: duration.value,
        custom_minutes: custom.value,
      })),
    );
    card.append(close, kind, title, duration, custom, actions);
    host.append(card);
  }

  async function poll() {
    try {
      const response = await fetch("/notifications/pending/");
      if (!response.ok) throw new Error("Could not check task reminders.");
      const result = await response.json();
      result.notifications.forEach(render);
    } catch (error) {
      console.error(error);
    }
  }

  poll();
  window.setInterval(poll, 10000);
})();
