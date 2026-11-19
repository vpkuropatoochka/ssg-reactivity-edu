const form = document.querySelector("#site-search");
const query = document.querySelector("#search-query");
const status = document.querySelector("#search-status");
const results = document.querySelector("#search-results");
const pages = JSON.parse(document.querySelector("#search-index").textContent);

const normalize = text => text.toLocaleLowerCase("ru").replaceAll("ё", "е");

function search() {
  const words = normalize(query.value).match(/[\p{L}\p{N}]+/gu) || [];
  const matches = words.length ? pages.filter(page => {
    const text = normalize(page.title + " " + page.text);
    return words.every(word => text.includes(word));
  }) : [];

  results.replaceChildren();
  for (const page of matches) {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = page.url;
    link.textContent = page.title;
    item.append(link);
    results.append(item);
  }

  status.textContent = words.length === 0 ? "" :
    matches.length ? `Найдено страниц: ${matches.length}.` : "Ничего не найдено.";
}

form.addEventListener("submit", event => {
  event.preventDefault();
  const url = new URL(location.href);
  url.search = query.value.trim() ? new URLSearchParams({q: query.value.trim()}) : "";
  history.replaceState(null, "", url);
  search();
});

query.value = (new URLSearchParams(location.search).get("q") || "").slice(0, 200);
search();
