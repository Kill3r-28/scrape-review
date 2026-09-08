(function () {
  function fallbackUrl(btn) {
    const fromBtn = btn?.dataset?.navBackFallback;
    if (fromBtn && fromBtn.startsWith("/")) return fromBtn;
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("return_to");
    if (fromQuery && fromQuery.startsWith("/")) return fromQuery;
    return "/";
  }

  function goBack(btn) {
    const ref = document.referrer;
    try {
      if (ref && new URL(ref).origin === window.location.origin && window.history.length > 1) {
        window.history.back();
        return;
      }
    } catch (_err) {
      /* ignore bad referrer */
    }
    window.location.href = fallbackUrl(btn);
  }

  document.querySelectorAll("[data-nav-back]").forEach((btn) => {
    btn.addEventListener("click", () => goBack(btn));
  });
})();
