/** Preferência de tema por aparelho (conveniência; não é dado crítico). */
export type Theme = "system" | "light" | "dark";
const KEY = "julius-theme";

export function getTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme = getTheme()) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

export function setTheme(theme: Theme) {
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    /* armazenamento indisponível: aplica só nesta sessão */
  }
  applyTheme(theme);
}
