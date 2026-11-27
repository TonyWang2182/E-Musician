(() => {
  "use strict";
  function t(value, ...values) {
    // Interpolated project names, prompts and model answers remain unchanged.
    if (Array.isArray(value) && Object.prototype.hasOwnProperty.call(value, "raw")) {
      return value.reduce((text, part, index) => text + (index ? String(values[index - 1] ?? "") : "") + part, "");
    }
    return String(value ?? "");
  }
  function applyStatic() {
    document.documentElement.lang = "en";
    document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
    for (const name of ["title", "placeholder", "aria-label"]) {
      document.querySelectorAll(`[data-i18n-${name}]`).forEach((node) => node.setAttribute(name, t(node.getAttribute(`data-i18n-${name}`))));
    }
  }
  window.emusicianI18n = { t, applyStatic, get locale() { return "en"; }, setLanguage() { applyStatic(); }, keys: [] };
  applyStatic();
})();
