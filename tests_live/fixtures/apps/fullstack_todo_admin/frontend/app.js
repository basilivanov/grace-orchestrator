const form = document.getElementById("item-form");
const titleInput = document.getElementById("title");
const itemsContainer = document.getElementById("items");

async function loadItems() {
  const response = await fetch("/api/items");
  const items = await response.json();
  itemsContainer.innerHTML = items
    .map((item) => `<div>${item.title}</div>`)
    .join("");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await fetch("/api/items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: titleInput.value }),
  });
  titleInput.value = "";
  await loadItems();
});

loadItems();
