import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "@/locales/en/common.json";
import vi from "@/locales/vi/common.json";

void i18n.use(initReactI18next).init({
  resources: { en: { common: en }, vi: { common: vi } },
  lng: localStorage.getItem("rm.lang") ?? "en",
  fallbackLng: "en",
  defaultNS: "common",
  interpolation: { escapeValue: false },
});

export function setLanguage(lang: "en" | "vi"): void {
  localStorage.setItem("rm.lang", lang);
  void i18n.changeLanguage(lang);
}

export default i18n;
