
(function () {
  const config = window.NOVA_WIKI || {};
  const searchInput = document.querySelector("[data-wiki-search]");
  const searchResults = document.querySelector("[data-search-results]");
  const sidebar = document.querySelector("[data-sidebar]");
  const toggle = document.querySelector("[data-nav-toggle]");

  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      sidebar.classList.toggle("open");
    });
  }

  if (!searchInput || !searchResults || !config.searchIndex) {
    return;
  }

  fetch(config.searchIndex)
    .then(function (response) { return response.json(); })
    .then(function (pages) {
      const renderResults = function (query) {
        const normalized = query.trim().toLowerCase();
        if (!normalized) {
          searchResults.classList.remove("visible");
          searchResults.innerHTML = "";
          return;
        }

        const matches = pages
          .filter(function (page) {
            const haystack = [page.title, page.excerpt, page.content].join(" ").toLowerCase();
            return haystack.indexOf(normalized) >= 0;
          })
          .slice(0, 8);

        searchResults.classList.add("visible");
        searchResults.innerHTML = matches.length
          ? matches.map(function (page) {
              return "<a href=\"" + page.href + "\"><strong>" + page.title + "</strong><span>" + (page.excerpt || "") + "</span></a>";
            }).join("")
          : "<a href=\"#\"><strong>No matches</strong><span>Try another keyword.</span></a>";
      };

      searchInput.addEventListener("input", function () {
        renderResults(searchInput.value);
      });
    })
    .catch(function () {
      searchResults.classList.remove("visible");
      searchResults.innerHTML = "";
    });
})();
