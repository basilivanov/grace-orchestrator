const countElement = document.getElementById("count");
const incrementButton = document.getElementById("inc");

incrementButton.addEventListener("click", () => {
  const current = Number(countElement.textContent || "0");
  countElement.textContent = String(current + 1);
});
